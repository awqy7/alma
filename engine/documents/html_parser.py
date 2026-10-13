"""Read saved document HTML without executing scripts or loading resources."""
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import re

from engine.ipc.contracts import AlmaError, ErrorCode

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
EXCLUDED={'script','style','noscript','iframe','object','svg','nav','button','input','select','textarea'}

@dataclass
class Node:
    tag:str
    attrs:dict
    path:str
    children:list=field(default_factory=list)

class Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root=Node('root',{},'');self.stack=[self.root];self.count=0
    def handle_starttag(self,tag,attrs):
        self.count+=1
        if self.count>100_000 or len(self.stack)>100: raise ValueError('HTML limits')
        parent=self.stack[-1];index=1+sum(isinstance(c,Node) and c.tag==tag for c in parent.children)
        node=Node(tag,dict(attrs),f'{parent.path}/{tag}[{index}]');parent.children.append(node)
        if tag not in VOID:self.stack.append(node)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for index in range(len(self.stack)-1,0,-1):
            if self.stack[index].tag==tag:
                del self.stack[index:];break
    def handle_data(self,data):self.stack[-1].children.append(data)

def hidden(node):
    style=re.sub(r'\s+','',node.attrs.get('style','').lower())
    return node.tag in EXCLUDED or 'hidden' in node.attrs or node.attrs.get('aria-hidden')=='true' or 'display:none' in style or 'visibility:hidden' in style

def text(node):
    if isinstance(node,str):return node
    if hidden(node):return ''
    return ' '.join(text(c) for c in node.children)

def parse_html(path:Path, encoding="utf-8-sig"):
    try:
        raw=path.read_bytes()
        if len(raw)>8*1024*1024:raise ValueError('HTML size')
        # No silent replacement of undecodable characters in evidence.
        source=raw.decode(encoding)
        if not re.search(r'<(?:!doctype\s+html|html|body|table|div|p|h[1-6])\b',source,re.I):raise ValueError('HTML expected')
        reader=Reader();reader.feed(source);reader.close()
        rows=[];section=''
        def visit(node):
            nonlocal section
            if isinstance(node,str) or hidden(node):return
            content=' '.join(text(node).split())
            children=[c for c in node.children if isinstance(c,Node) and not hidden(c)]
            if node.tag in {'h1','h2','h3','h4','caption'} or content.upper().startswith('TABELA COM DADOS PARA') and len(content)<90:
                section=content
            if node.tag=='tr':
                cells=[c for c in children if c.tag in {'td','th'}]
                content=' | '.join(' '.join(text(c).split()) for c in cells)
                rows.append({'text':content,'bbox':None,'html_location':node.path,'section':section})
                return
            if content and (node.tag in {'p','h1','h2','h3','h4','li','caption'} or not children):
                rows.append({'text':content,'bbox':None,'html_location':node.path,'section':section})
                return
            # Direct text nodes in generic containers must not disappear.
            direct=' '.join(c.strip() for c in node.children if isinstance(c,str) and c.strip())
            if direct:rows.append({'text':direct,'bbox':None,'html_location':node.path,'section':section})
            for child in children:visit(child)
        visit(reader.root)
        return {'sha256':sha256(raw).hexdigest(),'format':'HTML','pages':[{'page':None,'method':'HTML_DOM','text':'\n'.join(r['text'] for r in rows),'rows':rows,'blocks':[]}]}
    except Exception:
        raise AlmaError(ErrorCode.NOT_VERIFIABLE,'html_parsing') from None
