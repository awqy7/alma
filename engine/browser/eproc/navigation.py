"""Navigate existing DOM links only. Never construct eproc endpoints or query bodies."""
from urllib.parse import urljoin,urlsplit,parse_qs
import re
from engine.ipc.contracts import AlmaError,ErrorCode

def checked_link(origin,current,href,actions):
    url=urljoin(current,href or '')
    parsed=urlsplit(url);query=parse_qs(parsed.query)
    if parsed.username or parsed.password or f'{parsed.scheme}://{parsed.netloc}'!=origin or query.get('acao') not in [[a] for a in actions]:
        raise AlmaError(ErrorCode.UI_CHANGED,'navigation_link')
    return url,query

def canonical_process(value):return re.sub(r'\D','',value or '')

async def existing_links(page,origin,actions):
    result={}
    for element in await page.locator('a[href]').all():
        href=await element.get_attribute('href')
        try:url,query=checked_link(origin,page.url,href,actions)
        except AlmaError:continue
        # Fragments in toolbars are not navigation to a different requisition.
        if urlsplit(url).fragment:continue
        result[url]=(query,element)
    return result

async def go(session,page,url):
    await session.require_session()
    response=await page.goto(url,wait_until='domcontentloaded')
    session.page=page
    await session.require_session()
    if response and response.status==429:raise AlmaError(ErrorCode.RATE_LIMITED,'navigation',True)
    if response and response.status>=500:raise AlmaError(ErrorCode.HTTP_ERROR,'navigation',True)
    if response and response.status>=400:raise AlmaError(ErrorCode.HTTP_ERROR,'navigation')
