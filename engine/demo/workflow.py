"""Real DOM fills and POSTs, strictly restricted to a newly owned synthetic server."""
import asyncio
import base64
from datetime import datetime
from decimal import Decimal
from engine.demo.site import DemoSite
from engine.documents.inspection import inspect_documents,sample_documents
from engine.ipc.contracts import AlmaError,ErrorCode
from engine.extraction.normalizers import money

class DemoWorkflow:
    def __init__(self,session,root,emit):
        if not session.fixture_mode:raise AlmaError(ErrorCode.DISCOVERY_REQUIRED,'demo_boundary')
        self.site=DemoSite();self.session=session;self.root=root;self.emit=emit;self.applied=False
    async def start(self,show_browser):
        await self.session.connect(self.site.url,headless=not show_browser)
        self.items=sample_documents(self.root,'recording')
        data=inspect_documents(self.items,self.root)
        data['official_total']='2400.00';data['official_base_date']='2026-10';data['expected_process']='00000000020260000001'
        return data
    async def apply(self,plan):
        await self.session.require_session()
        if self.session.page.url.rstrip('/')!=self.site.url or self.applied:
            raise AlmaError(ErrorCode.NOT_VERIFIABLE,'demo_identity_or_replay')
        if set(plan)!={'total','arrears','expert','base_date'}:raise AlmaError(ErrorCode.IPC_ERROR,'demo_plan')
        for key in ['total','arrears','expert']:
            if not isinstance(plan[key],str) or Decimal(plan[key])<=0:raise AlmaError(ErrorCode.NOT_VERIFIABLE,'demo_value')
        date=datetime.strptime(plan['base_date'],'%Y-%m').strftime('%m/%Y')
        self.applied=True # Never retry a possibly committed sequence.
        page=self.session.page
        async def fill(selector,value):
            locator=page.locator(selector)
            if await locator.count()!=1:raise AlmaError(ErrorCode.UI_CHANGED,'demo_selector')
            await locator.fill(value);actual=await locator.input_value()
            if actual!=value:raise AlmaError(ErrorCode.NOT_VERIFIABLE,'readback')
        async def save(selector,count,phase):
            await page.locator(selector).click()
            await page.wait_for_function('(n)=>document.body.dataset.saves===String(n)',arg=count,timeout=10000)
            self.emit({'version':1,'type':'EVENT','name':'DEMO_STEP','payload':{'phase':phase,'mode':'DEMO','saved_in_demo':True}})
        formatted=lambda key:format(Decimal(plan[key]),'.2f').replace('.',',')
        await fill('#txtValorTotal',formatted('total'));await save('#btnSalvar',1,'HEADER_SAVED')
        await page.locator('#selPrecRpv').select_option('R');await page.locator('#selEspecieRequisicao').select_option('1')
        await fill('#txtValorTotalBenefi',formatted('arrears'));await fill('#txtDtaBase',date)
        await save('#btnSalvarBeneficiario',2,'BENEFICIARY_SAVED')
        await page.locator('#selNumCodTipoHonorario').select_option('51')
        await fill('#txtValorTotalHono',formatted('expert'));await fill('#txtDtaBaseHono',date)
        await save('#btnSalvarHonorario',3,'FEE_SAVED')
        # Re-open from the server: changing only input.value cannot satisfy this check.
        await page.reload();await page.wait_for_function('()=>document.body.dataset.saves==="3"')
        import json
        stored=json.loads(await page.locator('#result').inner_text())
        if any(str(money(stored[section]['total']))!=plan[key] for section,key in [('header','total'),('beneficiary','arrears'),('fee','expert')]):
            raise AlmaError(ErrorCode.NOT_VERIFIABLE,'saved_value')
        if any(stored[section]['base']!=date for section in ['beneficiary','fee']):raise AlmaError(ErrorCode.NOT_VERIFIABLE,'saved_date')
        screenshot=base64.b64encode(await page.screenshot(full_page=True)).decode()
        return {'stored':stored,'screenshot':'data:image/png;base64,'+screenshot,'mode':'DEMO','official_changes':0}
    async def close(self):
        await self.session.close()
        await asyncio.to_thread(self.site.close)
