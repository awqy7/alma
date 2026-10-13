import React, {useEffect, useState, useRef} from 'react';
import {invoke, isTauri} from '@tauri-apps/api/core';
import {listen} from '@tauri-apps/api/event';
import {create} from 'zustand';

type Evidence={document_name:string;event:string|null;page:number|null;html_location?:string;raw_text:string;sha256:string};
type Field={field:string;status:string;eproc_raw:string|null;document_raw:string[];rule_id:string;evidence:Evidence[]};
type Report={process_id:string;requisition_id:string;created_at:string;fields:Field[];document_review?:DocumentReview;coverage:Record<string,string>};
type DocumentReview={supervised_plan?:{ready:boolean};checks:{field:string;status:string;expected:string|null;provided:string|null;reason:string}[];observations:{field:string;status:string;value:string|null;reason:string;evidence:{document_name:string;event:string|null;page:number|null;html_location?:string;text:string;sha256:string}[]}[];scope_notice:string};
type Job={id:string;state:string;updated_at:string};
type Trace={timestamp?:string;action?:string;state?:string;error_code?:string;job_id?:string;name?:string;payload?:any};
type ExecutionRecord={id:string;job_id?:string;plan:any;result:any;executed_at:string};
type QueueItem={process_number:string;requisition_id:string;kind:string;state:string;error_code:string|null};
type Queue={id:string;localizer:string;status:string;error_code:string|null;items:QueueItem[]};
type Data={reports:Report[];jobs:Job[];events:Trace[];queue?:Queue|null;executions?:ExecutionRecord[]};

const phase:Record<string,string>={
  OPEN_LOCALIZER:'Localizador aberto',LIST_PROCESSES:'Fila lida',OPEN_PROCESS:'Processo aberto',
  OPEN_REQUISITION:'RPV aberta',DISCONNECTED:'Navegador desconectado',CONNECTING:'Conectando',
  AUTHENTICATED:'Sessão autenticada',REAUTH_REQUIRED:'Faça login novamente',QUEUED:'Aguardando',
  SESSION_CHECK:'Conferindo a sessão',OPENING_PROCESS:'Identificando o processo',
  READING_REQUISITION:'Lendo a RPV',INDEXING_DOCUMENTS:'Localizando documentos',
  DOWNLOADING:'Obtendo documentos',PARSING:'Lendo o PDF/HTML',EXTRACTING:'Localizando valores e datas',
  NORMALIZING:'Padronizando os dados',RECONCILING:'Comparando documento e cadastro',
  APPLYING_PLAN:'Gravando alterações no eproc',PLAN_APPLIED:'Gravação concluída no eproc',
  HEADER_SAVED:'Cabeçalho da RPV salvo',BENEFICIARY_SAVED:'Beneficiário salvo no subformulário',
  FEE_SAVED:'Honorário salvo no subformulário',VERIFIED:'Página recarregada e conferida',
  VALIDATED:'Análise concluída',PAUSED:'Pausado',EXCEPTION:'Precisa de atenção',FAILED:'Execução interrompida'
};

const verdict:Record<string,string>={VALIDATED:'Confere',DIVERGENT:'Diferente do documento',ABSENT:'Dado ausente',NOT_VERIFIABLE:'Não foi possível conferir',CONFLICTING_SOURCES:'Documentos com valores diferentes'};
const fieldNames:Record<string,string>={total_value:'Valor total',principal:'Principal',interest:'Juros',selic:'Selic',irpf:'IRPF',pss:'PSS',base_date:'Data-base',filing_date:'Ajuizamento',transition_date:'Trânsito em julgado',subject:'Assunto',entity:'Entidade',process_number:'Processo'};
const reasons:Record<string,string>={VALIDATED:'Os valores normalizados são iguais segundo a regra deste campo.',DIVERGENT:'Os valores normalizados diferem. Consulte o trecho antes de corrigir manualmente.',ABSENT:'Existe fonte documental, mas o campo do cadastro está vazio.',NOT_VERIFIABLE:'A leitura, a vinculação da fonte ou a regra disponível não permite concluir.',CONFLICTING_SOURCES:'Há mais de um valor documental. A ALMA não escolheu um em silêncio.'};
const readablePhase=(value:string)=>phase[value.replaceAll('"','')]??value;

function readableError(error:unknown){
  const message=error instanceof Error?error.message:String(error);
  const explanations:Record<string,string>={
    BROWSER_PROFILE_IN_USE:'O navegador ALMA já está aberto em outra execução. Feche essa outra execução da ALMA e tente novamente. Seu perfil e login serão preservados.',
    BROWSER_NAVIGATION_FAILED:'Não foi possível abrir o endereço do eproc. Confira o endereço e a conexão; depois tente novamente.',
    TIMEOUT:'O navegador demorou demais para responder. Tente abrir novamente; seu perfil foi preservado.',
    HTTP_ERROR:'O endereço do eproc retornou um erro. Confira o endereço e tente novamente.'
  };
  return explanations[message]??message;
}

function formatMoney(value:string|null){
  if(!value) return 'Não determinado';
  const [whole, cent='00']=value.split('.');
  return `R$ ${whole.replace(/\B(?=(\d{3})+(?!\d))/g,'.')},${cent.padEnd(2,'0')}`;
}

function formatDate(value:string|null){
  if(!value) return 'Não determinado';
  if(value.length===7) return `${value.slice(5)}/${value.slice(0,4)}`;
  return value.split('-').reverse().join('/');
}

const useAlma=create<Data & {setData:(data:Data)=>void;push:(event:Trace)=>void}>(set=>({
  reports:[],jobs:[],events:[],executions:[],
  setData:data=>set(data),
  push:event=>set(s=>({events:[event,...s.events].slice(0,500)}))
}));

export default function Operations({onBusyChange}:{onBusyChange?:(busy:boolean)=>void}){
  const {reports,jobs,events,executions,queue,setData,push}=useAlma();
  const [localizer,setLocalizer]=useState('Concluso Decisão RPV');
  const [process,setProcess]=useState('');
  const [url,setUrl]=useState('https://eproc1g.trf6.jus.br/eproc/');
  const [session,setSession]=useState('DISCONNECTED');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [selected,setSelected]=useState(0);
  const [exceptions,setExceptions]=useState(true);
  const [planConfirmed,setPlanConfirmed]=useState(false);
  const [execProgress,setExecProgress]=useState('');
  const [execResult,setExecResult]=useState<any>(null);
  const [autoRead,setAutoRead]=useState(true);
  const [connected,setConnected]=useState(false);
  const autoArmed=useRef(true), autoStarted=useRef(false), operating=useRef(false), stopQueue=useRef(false);
  async function api<T>(command:string,path:string,args:Record<string,unknown>={}):Promise<T>{
    if(isTauri())return invoke<T>(command,args);
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(args)});
    const body=await response.json();if(!response.ok)throw new Error(body.error||'EXCEPTION');return body;
  }
  async function runQueue(){
    if(operating.current)return;
    autoStarted.current=true;stopQueue.current=false;
    await act(async()=>{
      let current=await api<Queue>('start_queue','/api/queue/start',{localizer});
      await refresh();
      while(current.status==='RUNNING'&&!stopQueue.current){
        current=await api<Queue>('queue_step','/api/queue/step');
        await refresh();
        if(current.error_code){
          setError(current.error_code);
          if(['REAUTH_REQUIRED','SESSION_EXPIRED'].includes(current.error_code)){
            setSession('REAUTH_REQUIRED');autoStarted.current=false;
          }
        }
        if(current.status==='RUNNING')await new Promise(resolve=>setTimeout(resolve,1000));
      }
      if(stopQueue.current)await api('pause_queue','/api/queue/pause');
    });
  }
  async function stopAutomatic(){
    stopQueue.current=true;autoArmed.current=false;setAutoRead(false);
    try{await api('pause_queue','/api/queue/pause');await refresh();}catch(e){setError(String(e));}
  }
  useEffect(()=>{
    if(!connected)return;
    let cancelled=false;
    const timer=setInterval(async()=>{
      if(cancelled||operating.current)return;
      operating.current=true;
      try{
        const result=await api<{state:string}>('check_session','/api/session');
        if(cancelled)return;
        setSession(result.state);
        if(result.state==='AUTHENTICATED'&&autoArmed.current&&!autoStarted.current){
          operating.current=false;await runQueue();
        }
      }catch(e){if(!cancelled)setError(String(e));}
      finally{operating.current=false;}
    },3000);
    return()=>{cancelled=true;clearInterval(timer);};
  },[connected,localizer]);


  async function refresh(){
    if(!isTauri()){
      try{
        const r=await fetch('/api/status');
        if(r.ok){
          const d=await r.json();
          setData(d);
        }
      }catch{}
      return;
    }
    setData(await invoke<Data>('status'));
  }

  useEffect(()=>{
    void refresh().catch(()=>setError('Não foi possível ler a auditoria.'));
    if(!isTauri()) return;
    const subscription=listen<Trace>('alma:event',event=>{
      push(event.payload);
      if(event.payload?.name==='REAL_EXECUTION_STEP'){
        const phaseName = event.payload.payload?.phase;
        if(phaseName) setExecProgress(readablePhase(phaseName));
      }
    });
    return ()=>{void subscription.then(stop=>stop());};
  },[]);

  async function act(action:()=>Promise<unknown>){
    operating.current=true;
    setBusy(true);
    onBusyChange?.(true);
    setError('');
    try{
      await action();
    }catch(e){
      setError(readableError(e));
      if(/REAUTH_REQUIRED|SESSION_EXPIRED/.test(String(e))){setSession('REAUTH_REQUIRED');autoStarted.current=false;}
    }finally{
      try{ await refresh(); }catch{ setError(prev=>prev||'Não foi possível ler a auditoria.'); }
      operating.current=false;
      setBusy(false);
      onBusyChange?.(false);
    }
  }

  const all=reports.flatMap(r=>r.fields);
  const active=reports[selected];
  const stats=[
    ['RPVs analisadas',reports.length],
    ['Campos conferidos',all.filter(f=>['VALIDATED','DIVERGENT'].includes(f.status)).length],
    ['Divergências',all.filter(f=>f.status==='DIVERGENT').length],
    ['Não verificáveis',all.filter(f=>f.status==='NOT_VERIFIABLE').length]
  ];

  // Derived plan values
  const planTotal = active?.document_review?.checks.find(c=>c.field==='total')?.expected ?? null;
  const planBase = active?.document_review?.checks.find(c=>c.field==='base_date')?.expected ?? null;
  const planArrears = active?.document_review?.observations.find(o=>o.field==='arrears_amount')?.value ?? null;
  const planExpert = active?.document_review?.observations.find(o=>o.field==='expert_amount')?.value ?? null;
  const canApply = Boolean(planTotal && planArrears && planExpert && planBase && session==='AUTHENTICATED' && active?.coverage.beneficiaries==='read' && active?.coverage.fees==='read' && active?.document_review?.supervised_plan?.ready===true);

  async function handleExecuteRealPlan(){
    if(!canApply || !active) return;
    operating.current=true;
    setBusy(true);
    onBusyChange?.(true);
    setError('');
    setExecResult(null);
    setExecProgress('Iniciando automação no eproc...');
    try{
      const payload={
        expected_process: active.process_id,
        total: planTotal,
        arrears: planArrears,
        expert: planExpert,
        base_date: planBase
      };
      let res: any;
      if(isTauri()){
        res = await invoke('apply_real_plan', {plan: payload});
      }else{
        const r = await fetch('/api/apply_real_plan', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
        const body = await r.json();
        if(!r.ok) throw new Error(body.error || 'Falha ao executar alterações no eproc.');
        res = body;
      }
      setExecResult(res);
      await refresh();
    }catch(e:any){
      setError(e.message || String(e));
    }finally{
      operating.current=false;
      setBusy(false);
      onBusyChange?.(false);
      setExecProgress('');
    }
  }

  return <main>
    <header><div className="brand">ALMA <span>Automação Integrada do eproc</span></div><b>Modo Real</b></header>
    <h1>Modo real · Leitura automática da fila</h1>
    <p>Faça login para iniciar a conferência da fila configurada. Acompanhe os resultados, as fontes e as exceções.</p>
    
    {!isTauri()&&<aside>Conecte ao eproc para testar a leitura e automação real. Um navegador Chromium será aberto para você fazer login.</aside>}
    
    <section className="controls">
      <label>Endereço do eproc
        <input value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://eproc1g.trf6.jus.br/eproc/"/>
      </label>
      <button disabled={busy||!url||session!=='DISCONNECTED'} onClick={()=>void act(async()=>{
        let r:{state:string};
        if(isTauri()){
          r=await invoke<{state:string}>('connect',{url});
        }else{
          const resp=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
          const body=await resp.json();
          if(!resp.ok) throw new Error(body.error||'Falha ao conectar');
          r=body;
        }
        setSession(r.state);setConnected(true);autoStarted.current=false;autoArmed.current=autoRead;
      })}>Abrir navegador eproc</button>
      <button disabled={busy} onClick={()=>void act(async()=>{
        let r:{state:string};
        if(isTauri()){
          r=await invoke<{state:string}>('check_session');
        }else{
          const resp=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          const body=await resp.json();
          if(!resp.ok) throw new Error(body.error||'Sem conexão');
          r=body;
        }
        setSession(r.state);
      })}>Verificar login</button>
      <button disabled={busy} onClick={()=>void act(async()=>{
        if(isTauri()){
          await invoke('restart_worker');
        }else{
          await fetch('/api/disconnect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        }
        setSession('DISCONNECTED');setConnected(false);autoStarted.current=false;
      })}>Reiniciar conexão</button>
      <span role="status">{readablePhase(session)}</span>
    </section>

    <section aria-label="Leitura automática">
      <h2>Leitura automática após o login</h2>
      <label><input type="checkbox" checked={autoRead} disabled={busy} onChange={e=>{setAutoRead(e.target.checked);autoArmed.current=e.target.checked;if(e.target.checked)autoStarted.current=false;}}/> Ler todas as RPVs do localizador configurado</label>
      <p>Faça login no navegador aberto pela ALMA. A sessão será detectada automaticamente. A fila lê uma RPV por vez; não executa preenchimento nem salvamento.</p>
      <button disabled={busy||session!=='AUTHENTICATED'} onClick={()=>{autoArmed.current=true;setAutoRead(true);void runQueue();}}>Iniciar / continuar fila</button>
      <button disabled={!busy&&queue?.status!=='RUNNING'} onClick={()=>void stopAutomatic()}>Pausar leitura automática</button>
      {queue&&<><p role="status">Fila: {queue.localizer} · {queue.status==='COMPLETED'?'Varredura concluída; confira as exceções':queue.status==='PAUSED'?'Pausada':queue.status==='DISCOVERING'?'Localizando processos':'Em leitura'} · {queue.items.filter(i=>i.kind==='RPV'&&i.state==='COMPLETED').length} RPVs analisadas / {queue.items.filter(i=>i.kind==='RPV').length} encontradas · {queue.items.filter(i=>i.state==='EXCEPTION').length} exceções</p>
      <table><thead><tr><th>Processo</th><th>RPV</th><th>Etapa</th><th>Ocorrência</th></tr></thead><tbody>{queue.items.filter(i=>i.kind==='RPV'||i.state!=='COMPLETED').slice(0,100).map(i=><tr key={i.process_number+':'+i.requisition_id}><td>{i.process_number}</td><td>{i.requisition_id||'Descobrindo RPVs'}</td><td>{{PENDING:'Aguardando',RUNNING:'Lendo',COMPLETED:'Analisada',EXCEPTION:'Revisão necessária'}[i.state]??i.state}</td><td>{i.error_code??'—'}</td></tr>)}</tbody></table></>}
    </section>
    <section className="controls">
      <label>Localizador<input disabled={busy} value={localizer} onChange={e=>setLocalizer(e.target.value)}/></label>
      <label>Processo<input value={process} onChange={e=>setProcess(e.target.value)}/></label>
      <button disabled={busy||session!=='AUTHENTICATED'||!process||!localizer} onClick={()=>void act(async()=>{
        if(isTauri()){
          await invoke('open_target',{localizer,processNumber:process});
        }else{
          // Open localizer then process then requisition via HTTP
          let resp=await fetch('/api/eproc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:'OPEN_LOCALIZER',payload:{name:localizer}})});
          if(!resp.ok){const b=await resp.json();throw new Error(b.error||'Falha ao abrir localizador');}
          resp=await fetch('/api/eproc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:'OPEN_PROCESS',payload:{process_number:process}})});
          if(!resp.ok){const b=await resp.json();throw new Error(b.error||'Falha ao abrir processo');}
          resp=await fetch('/api/eproc',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:'OPEN_REQUISITION',payload:{}})});
          if(!resp.ok){const b=await resp.json();throw new Error(b.error||'Falha ao abrir requisição');}
        }
      })}>Abrir RPV pela fila</button>
    </section>

    <section className="controls">
      <button disabled={busy||session!=='AUTHENTICATED'} onClick={()=>void act(async()=>{
        if(isTauri()){
          await invoke('review',{job:null});
        }else{
          const resp=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          const body=await resp.json();
          if(!resp.ok) throw new Error(body.error||'Falha ao revisar RPV');
          push({timestamp:new Date().toISOString(),action:'REVIEW',state:'VALIDATED'});
        }
      })}>Revisar RPV aberta</button>
      <button disabled={!busy} onClick={()=>void (isTauri()?invoke('pause'):Promise.resolve()).catch(e=>setError(String(e)))}>Pausar após etapa atual</button>
      {busy&&<span role="status">{execProgress || (events[0]?.state?readablePhase(events[0].state):'Em execução…')}</span>}
      {error&&<strong role="alert">{error==='DISCOVERY_REQUIRED'?'Esta etapa do eproc ainda precisa ser mapeada. Nenhuma alteração foi feita.':error==='UI_CHANGED'?'Nenhuma tela de Ofício Requisitório (RPV) aberta foi localizada no navegador. Abra o processo e clique em "Ofício Requisitório" para iniciar a conferência.':error==='REAUTH_REQUIRED'?'Faça login no navegador ALMA e verifique a sessão novamente.':error}</strong>}
    </section>

    {active?.document_review && (
      <section className="supervised-plan" aria-label="Plano de execução no eproc">
        <h2>Plano de Automação · Execução no eproc</h2>
        <p>Plano documental. O salvamento depende da leitura completa dos itens e de um plano validado; ter valores extraídos não basta para habilitá-lo.</p>
        
        <table style={{width:'100%',margin:'14px 0'}}>
          <thead>
            <tr>
              <th>Campo / Item</th>
              <th>Valor Atual no eproc</th>
              <th>Valor Proposto pela ALMA</th>
              <th>Regra / Destino</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Total do Ofício</strong></td>
              <td>{active.fields.find(f=>f.field==='total_value')?.eproc_raw ?? 'Não lido'}</td>
              <td><strong style={{color:'#185abc'}}>{formatMoney(planTotal)}</strong></td>
              <td>Soma dos atrasados e perito (#txtValorTotal)</td>
            </tr>
            <tr>
              <td><strong>Beneficiário (Atrasados)</strong></td>
              <td>{active.fields.find(f=>f.field==='principal')?.eproc_raw ?? 'Não lido'}</td>
              <td><strong style={{color:'#185abc'}}>{formatMoney(planArrears)}</strong></td>
              <td>Data-base: {formatDate(planBase)} · Subformulário #ifrSubFrm</td>
            </tr>
            <tr>
              <td><strong>Devolução ao Perito</strong></td>
              <td>Não cadastrado / A apurar</td>
              <td><strong style={{color:'#185abc'}}>{formatMoney(planExpert)}</strong></td>
              <td>Data-base: {formatDate(planBase)} · Tipo 51 · Subformulário #ifrSubFrm</td>
            </tr>
          </tbody>
        </table>

        <div style={{marginTop:'18px',padding:'14px',background:'#f0f4f9',borderRadius:'8px'}}>
          <label style={{display:'flex',gap:'10px',alignItems:'center',cursor:'pointer'}}>
            <input type="checkbox" checked={planConfirmed} disabled={busy} onChange={e=>setPlanConfirmed(e.target.checked)}/>
            <span><strong>Confirmo os valores conferidos acima</strong> e autorizo o preenchimento e salvamento automático no eproc.</span>
          </label>
        </div>

        <div style={{marginTop:'16px'}}>
          <button
            className="primary"
            style={{background:'#137333',borderColor:'#137333',padding:'10px 20px',fontSize:'15px',fontWeight:600}}
            disabled={busy || !planConfirmed || !canApply}
            onClick={()=>void handleExecuteRealPlan()}
          >
            Executar alterações no eproc agora
          </button>
          {busy && execProgress && <span role="status" style={{marginLeft:'14px',fontWeight:500}}>{execProgress}</span>}
        </div>

        {execResult && (
          <div className="decision-note" style={{background:'#e6f4ea',border:'1px solid #137333',marginTop:'20px'}}>
            <h3 style={{color:'#137333',margin:0}}>✓ Execução concluída com sucesso no eproc!</h3>
            <p><strong>{execResult.official_changes}</strong> alterações gravadas e verificadas por releitura no eproc.</p>
            <ul>
              <li>Cabeçalho salvo com valor total: <strong>{execResult.execution?.header?.readback ?? formatMoney(planTotal)}</strong></li>
              <li>Beneficiário salvo no subformulário: <strong>{execResult.execution?.beneficiary?.arrears}</strong> (Data-base: {execResult.execution?.beneficiary?.base_date})</li>
              <li>Honorários periciais salvos no subformulário: <strong>{execResult.execution?.fee?.expert}</strong> (Data-base: {execResult.execution?.fee?.base_date})</li>
            </ul>
            {execResult.execution?.screenshot && (
              <details open style={{marginTop:'14px'}}>
                <summary><strong>Captura da tela do eproc ao final da execução</strong></summary>
                <img
                  src={execResult.execution.screenshot}
                  alt="Tela do eproc com as alterações salvas pela automação ALMA"
                  style={{width:'100%',border:'1px solid #ccd8e5',marginTop:'10px',borderRadius:'6px'}}
                />
              </details>
            )}
          </div>
        )}
      </section>
    )}

    <section className="metrics">
      {stats.map(([label,value])=><article key={label}><span>{label}</span><strong>{value}</strong></article>)}
    </section>

    <h2>Fila de revisão</h2>
    {!jobs.length ? <p>Nenhuma execução registrada.</p> : (
      <table>
        <thead><tr><th>Execução</th><th>Fase</th><th>Atualização</th><th>Retomada</th></tr></thead>
        <tbody>{jobs.map(j=><tr key={j.id}><td>{j.id.slice(0,8)}</td><td>{readablePhase(j.state)}</td><td>{new Date(j.updated_at).toLocaleString('pt-BR')}</td><td>{['PAUSED','EXCEPTION','FAILED'].includes(j.state)&&<button disabled={busy} onClick={()=>void act(async()=>{
          if(isTauri()){
            await invoke('review',{job:j.id});
          }else{
            const resp=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job:j.id})});
            const body=await resp.json();
            if(!resp.ok) throw new Error(body.error||'Falha ao retomar leitura');
            push({timestamp:new Date().toISOString(),action:'REVIEW',state:'VALIDATED'});
          }
        })}>Continuar com nova leitura</button>}</td></tr>)}</tbody>
      </table>
    )}

    <h2>Resultados e evidências documentais</h2>
    {reports.length>0 && (
      <select aria-label="Selecionar relatório" value={selected} onChange={e=>setSelected(Number(e.target.value))}>
        {reports.map((r,i)=><option key={r.created_at} value={i}>{r.process_id} · {r.requisition_id}</option>)}
      </select>
    )}
    
    {active&&<aside>Cobertura desta leitura: {Object.entries(active.coverage).map(([section,state])=>`${section}: ${state}`).join(' · ')}. Campos fora da cobertura não foram validados.</aside>}
    
    <label className="filter">
      <input type="checkbox" checked={exceptions} onChange={e=>setExceptions(e.target.checked)}/> Mostrar somente campos para revisão
    </label>
    
    {!active ? <p>Os resultados aparecerão após executar a revisão da RPV aberta.</p> : (
      <table>
        <thead><tr><th>Campo</th><th>eproc</th><th>Documento</th><th>Resultado e fonte</th></tr></thead>
        <tbody>{active.fields.filter(f=>!exceptions||f.status!=='VALIDATED').map((f,i)=><tr key={i}><td>{fieldNames[f.field]??f.field}</td><td>{f.eproc_raw??'Não disponível'}</td><td>{f.document_raw.join(' / ')||'Sem fonte verificável'}</td><td><strong className={f.status==='DIVERGENT'?'divergent':''}>{verdict[f.status]??f.status}</strong><p>{reasons[f.status]}</p>{f.evidence.map((e,k)=><details key={k}><summary>{e.document_name} · Evento {e.event??'—'} · {e.page?`Página ${e.page}`:`HTML ${e.html_location??''}`}</summary><blockquote>{e.raw_text}</blockquote><small>Regra: {f.rule_id}<br/>SHA-256: {e.sha256}</small></details>)}</td></tr>)}</tbody>
      </table>
    )}

    {active?.document_review && (
      <section aria-label="Conferência dos documentos do processo">
        <h2>Valores e datas identificados nos documentos</h2>
        <p>{active.document_review.scope_notice}</p>
        <table>
          <thead><tr><th>Conferência</th><th>Documento / cálculo</th><th>eproc</th><th>Resultado</th></tr></thead>
          <tbody>{active.document_review.checks.map(c=><tr key={c.field}><td>{c.field==='total'?'Soma dos atrasados e perito':'Data-base pela proposta'}</td><td>{c.field.includes('date')?formatDate(c.expected):formatMoney(c.expected)}</td><td>{c.field.includes('date')?formatDate(c.provided):formatMoney(c.provided)}</td><td><strong>{verdict[c.status]??({DERIVED:'Calculada pela proposta',CALCULATED:'Calculado',FOUND:'Localizado'}[c.status]??c.status)}</strong><p>{c.reason}</p></td></tr>)}</tbody>
        </table>
        {active.document_review.observations.filter(o=>['arrears_amount','expert_amount','proposal_date'].includes(o.field)).map(o=><article key={o.field}><h3>{{arrears_amount:'Atrasados',expert_amount:'Valor solicitado ao perito',proposal_date:'Data da proposta'}[o.field]}: {o.field.includes('date')?formatDate(o.value):formatMoney(o.value)}</h3><p>{o.reason}</p>{o.evidence.map((e,i)=><details key={i}><summary>{e.document_name} · Evento {e.event??'—'} · {e.page?`Página ${e.page}`:'Documento HTML'}</summary><blockquote>{e.text}</blockquote><small>{e.html_location}<br/>SHA-256: {e.sha256}</small></details>)}</article>)}
      </section>
    )}

    <h2>Trilha de execução e auditoria</h2>
    <ol>{events.slice(0,30).map((e,i)=><li key={i}>{e.timestamp?new Date(e.timestamp).toLocaleTimeString('pt-BR'):''} {readablePhase(e.action||e.state||'')} {e.error_code}</li>)}</ol>
  </main>;
}
