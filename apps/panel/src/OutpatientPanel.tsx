import { useEffect, useState } from 'react'
import realisticExample from '../../../examples/outpatient_realistic_synthetic_zh.json'
import { api, request } from './api'
import { TranscriptEditor } from './components/TranscriptEditor'
import type { Turn } from './types'

const SECTIONS = {
  chief_complaint: '主诉', present_illness: '现病史', past_history: '既往史',
  allergy_history: '过敏史', medication_history: '用药史', physical_examination: '体格检查',
  investigations: '辅助检查', assessment: '初步诊断', plan: '治疗处理意见',
} as const
const keys = Object.keys(SECTIONS) as (keyof typeof SECTIONS)[]
type Item = { text: string; assertion: 'present'|'negated'|'uncertain'; origin: 'transcript'|'manual'; reported_by: string; evidence: {turn_id:number;quote:string}[]; reviewed: boolean }
type Section = {status:'documented'|'unknown'|'conflict';items:Item[];reviewed:boolean}
type Document = Record<keyof typeof SECTIONS, Section>
type Patient = {patient_id: string|null; name:string|null; sex:'male'|'female'|'other'|'unknown';age:number|null}
type Encounter = {department:string|null;visit_type:'initial'|'follow_up'|'unknown';visited_at:string|null}
type Draft = {id:string;version:number;state:string;document:Document;patient:Patient;encounter:Encounter;turns:Turn[];reviewer:string|null;model_metadata?:{elapsed_s?:number}}
const SAMPLE: Turn[] = [
  {turn_id:1,speaker:'doctor',text:'今天哪里不舒服？'},
  {turn_id:2,speaker:'patient',text:'我咳嗽两天了，还有咽痛，没有发热。'},
  {turn_id:3,speaker:'doctor',text:'以前有什么疾病？药物过敏情况呢？'},
  {turn_id:4,speaker:'patient',text:'我有高血压病史。青霉素过敏情况我不知道。'},
  {turn_id:5,speaker:'patient',text:'我昨天吃了布洛芬，一次200毫克。'},
  {turn_id:6,speaker:'doctor',text:'今天测量体温36.8摄氏度，咽部充血。'},
  {turn_id:7,speaker:'patient',text:'昨天的血常规报告我没带，不知道结果。'},
  {turn_id:8,speaker:'doctor',text:'初步考虑上呼吸道感染，尚未确诊。'},
  {turn_id:9,speaker:'doctor',text:'建议多饮水、休息，三天后复诊；如果出现呼吸困难请及时就医。'},
]
const body = (value:unknown, method='POST') => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(value)})

export default function OutpatientPanel() {
  const [logged, setLogged] = useState(Boolean(sessionStorage.getItem('smartmed_token')))
  const [staff, setStaff] = useState(sessionStorage.getItem('smartmed_staff')||'demo_frontend')
  const [password,setPassword]=useState('')
  const [turns,setTurns]=useState<Turn[]>([{turn_id:1,speaker:'patient',text:''}])
  const [transcriptReviewed,setTranscriptReviewed]=useState(false)
  const [draft,setDraft]=useState<Draft|null>(null)
  const [document,setDocument]=useState<Document|null>(null)
  const [patient,setPatient]=useState<Patient>({patient_id:null,name:null,sex:'unknown',age:null})
  const [encounter,setEncounter]=useState<Encounter>({department:null,visit_type:'unknown',visited_at:null})
  const [checked,setChecked]=useState<string[]>([])
  const [identityReviewed,setIdentityReviewed]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false)
  const [ready,setReady]=useState(false)
  const [asrText,setAsrText]=useState('')
  const dirty = Boolean(draft && (JSON.stringify(document)!==JSON.stringify(draft.document) || JSON.stringify(patient)!==JSON.stringify(draft.patient) || JSON.stringify(encounter)!==JSON.stringify(draft.encounter)))
  function apply(result:Draft) {
    setDraft(result);setDocument(result.document);setPatient(result.patient);setEncounter(result.encounter);setTurns(result.turns)
    setChecked([]);setIdentityReviewed(false);history.replaceState(null,'',`?outpatient=${encodeURIComponent(result.id)}`)
  }
  useEffect(()=>{
    api.health().then(h=>setReady(h.status==='ready')).catch(()=>setReady(false))
    const id=new URLSearchParams(location.search).get('outpatient')
    if(logged && id) request<Draft>(`/v1/outpatient/drafts/${encodeURIComponent(id)}`).then(apply).catch(e=>setError(e.message))
  },[logged])
  async function run(task:()=>Promise<void>) {
    setBusy(true);setError('');setNotice('')
    try {await task()} catch(e) {setError(e instanceof Error?e.message:'服务错误')} finally {setBusy(false)}
  }
  function changeSection(key:keyof Document, items:Item[]) {
    if(!document)return
    setDocument({...document,[key]:{items,status:items.length?'documented':'unknown',reviewed:false}})
    setChecked([])
  }
  function editItem(key:keyof Document,index:number,patch:Partial<Item>) {
    if(!document)return
    changeSection(key,document[key].items.map((item,i)=>i===index?{...item,...patch,origin:'manual',reported_by:'clinician',evidence:[],reviewed:false}:item))
  }
  async function printRecord() {
    if(!draft)return
    // Open synchronously to avoid browsers blocking the window after an awaited fetch.
    const tab=window.open('','_blank')
    if(!tab)throw new Error('请允许打印窗口')
    try {
      const token=sessionStorage.getItem('smartmed_token')
      const response=await fetch(`/v1/outpatient/drafts/${draft.id}/print`,{headers:{Authorization:`Bearer ${token}`}})
      if(!response.ok)throw new Error('请先确认已保存的病历')
      const content=await response.text();tab.document.open();tab.document.write(content);tab.document.close();tab.focus();tab.print()
    } catch(e){tab.close();throw e}
  }
  return <div className="app-shell"><header className="site-header"><div className="brand"><strong>智医病历</strong><small>中国普通门诊 · outpatient.v1</small></div><div className="header-right"><span>{ready?'模型就绪':'模型不可用'}</span>{logged&&<button onClick={()=>run(async()=>{await request('/v1/auth/logout',{method:'POST'});sessionStorage.removeItem('smartmed_token');sessionStorage.removeItem('smartmed_staff');setLogged(false);setDraft(null);setDocument(null);setTurns([{turn_id:1,speaker:'patient',text:''}]);history.replaceState(null,'',location.pathname)})}>退出</button>}</div></header>
  <main className="page">{error&&<p className="feedback error" role="alert">{error}</p>}{notice&&<p className="feedback">{notice}</p>}
  {!logged?<form className="panel" onSubmit={e=>{e.preventDefault();run(async()=>{const result=await api.login(staff,password);sessionStorage.setItem('smartmed_token',result.access_token);sessionStorage.setItem('smartmed_staff',staff);setPassword('');setLogged(true)})}}><h2>员工登录</h2><label>员工编号<input aria-label="员工编号" value={staff} onChange={e=>setStaff(e.target.value)} /></label><label>密码<input aria-label="密码" type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} /></label><button disabled={busy}>登录</button></form>:<>
  <section className="panel"><h2>患者与就诊信息</h2><p>由登记系统或医生填写，模型不会猜测。未知可留空；导出前请核对。</p><div className="fact-grid">
  <label>姓名<input aria-label="姓名" value={patient.name||''} onChange={e=>setPatient({...patient,name:e.target.value||null})} disabled={busy}/></label>
  <label>患者编号<input aria-label="患者编号" value={patient.patient_id||''} onChange={e=>setPatient({...patient,patient_id:e.target.value||null})} disabled={busy}/></label>
  <label>年龄<input type="number" min="0" max="130" value={patient.age??''} onChange={e=>setPatient({...patient,age:e.target.value===''?null:Number(e.target.value)})} disabled={busy}/></label>
  <label>性别<select value={patient.sex} onChange={e=>setPatient({...patient,sex:e.target.value as Patient['sex']})} disabled={busy}><option value="unknown">未知</option><option value="male">男</option><option value="female">女</option><option value="other">其他</option></select></label>
  <label>科室<input aria-label="科室" value={encounter.department||''} onChange={e=>setEncounter({...encounter,department:e.target.value||null})} disabled={busy}/></label>
  <label>初诊 / 复诊<select value={encounter.visit_type} onChange={e=>setEncounter({...encounter,visit_type:e.target.value as Encounter['visit_type']})} disabled={busy}><option value="unknown">未指定</option><option value="initial">初诊</option><option value="follow_up">复诊</option></select></label>
  <label>就诊时间<input type="datetime-local" value={encounter.visited_at||''} onChange={e=>setEncounter({...encounter,visited_at:e.target.value||null})} disabled={busy}/></label></div></section>
  <div className="workspace" style={{display:'grid',gridTemplateColumns:'minmax(300px, 1fr) minmax(400px, 1.5fr)',gap:24,marginTop:24}}>
  <section className="panel"><h2>就诊对话</h2><p>先核对原文和角色，再生成病历。麦克风记录与自动分角色待接入。</p><TranscriptEditor turns={turns} disabled={Boolean(draft)||busy} onChange={value=>{setTurns(value);setTranscriptReviewed(false)}} />
  {!draft&&<><button disabled={busy} onClick={()=>{setTurns(SAMPLE.map(t=>({...t})));setTranscriptReviewed(false)}}>载入门诊示例</button><button disabled={busy} onClick={()=>{setTurns(realisticExample.turns.map(t=>({...t,speaker:t.speaker as Turn["speaker"]})));setTranscriptReviewed(false);setNotice("已载入32句合成门诊对话，含病史矛盾；并非真实患者病历。")}}>载入复杂对话（合成）</button><label>上传 WAV<input type="file" accept=".wav,audio/wav" disabled={busy} onChange={e=>{const file=e.target.files?.[0];if(file)run(async()=>{if(file.size>5000000)throw new Error('音频最大5 MB');const result=await api.transcribe(file);setAsrText(result.text);setNotice('请修正识别文字并手动分配到医生、患者或其他发言。');setTranscriptReviewed(false)})}} /></label>{asrText&&<textarea aria-label="识别原文" value={asrText} onChange={e=>setAsrText(e.target.value)}/>}
  <label><input type="checkbox" aria-label="已核对对话和角色" checked={transcriptReviewed} onChange={e=>setTranscriptReviewed(e.target.checked)} />已核对对话原文和每句角色</label><button className="primary-button" disabled={busy||!transcriptReviewed} onClick={()=>run(async()=>{if(turns.some(t=>!t.text.trim())||turns.reduce((n,t)=>n+t.text.length,0)>8000)throw new Error('请填写全部发言，对话最多8000字符');apply(await request<Draft>('/v1/outpatient/drafts',body({turns,transcript_reviewed:true,patient,encounter})));setNotice('病历已生成。请核对来源，保存修改后逐节确认。')})}>{busy?'正在处理…':'生成门诊病历'}</button></>}
  {draft&&<button onClick={()=>{setDraft(null);setDocument(null);setChecked([]);setIdentityReviewed(false);setTranscriptReviewed(false);setAsrText('');history.replaceState(null,'',location.pathname)}} disabled={busy}>新建记录</button>}</section>
  <section className="panel"><h2>门诊病历草稿 {draft&&<small>{draft.state==='confirmed'?'已确认':'待审核'} · v{draft.version}{draft.model_metadata?.elapsed_s !== undefined && ` · 生成 ${draft.model_metadata.elapsed_s.toFixed(1)} 秒`}</small>}</h2><p>缺失信息保留未知；医生判断和处置只记录已说出的内容。手动修改保留审核记录。</p>
  {document&&draft? <>{keys.map(key=><section key={key} className="outpatient-section"><h3>{SECTIONS[key]} {document[key].status==='conflict'&&<strong>存在冲突，需要解决</strong>}</h3>{!document[key].items.length&&<p>未记录 / 未知（不代表明确否认）</p>}{document[key].items.map((item,index)=><div className="clinical-item" key={index}><textarea aria-label={`${SECTIONS[key]}条目${index+1}`} value={item.text} disabled={busy} onChange={e=>editItem(key,index,{text:e.target.value})}/><select aria-label={`${SECTIONS[key]}状态${index+1}`} value={item.assertion} disabled={busy} onChange={e=>editItem(key,index,{assertion:e.target.value as Item['assertion']})}><option value="present">明确陈述</option><option value="negated">明确否认</option><option value="uncertain">不确定 / 怀疑</option></select><small>{item.origin==='manual'?'医生手动修改（不伪造原文引用）':`来源：${item.reported_by}`}</small>{item.evidence.map((e,i)=><blockquote key={i}>第{e.turn_id}句：{e.quote}</blockquote>)}<button disabled={busy} onClick={()=>changeSection(key,document[key].items.filter((_,i)=>i!==index))}>删除条目</button></div>)}<button disabled={busy} onClick={()=>changeSection(key,[...document[key].items,{text:'',assertion:'present',origin:'manual',reported_by:'clinician',evidence:[],reviewed:false}])}>＋医生补充</button><label><input type="checkbox" aria-label={`已审核${SECTIONS[key]}`} disabled={busy||dirty||draft.state==='confirmed'} checked={draft.state==='confirmed'||checked.includes(key)} onChange={e=>setChecked(e.target.checked?[...checked,key]:checked.filter(k=>k!==key))}/>已核对本节内容、来源及缺失信息</label></section>)}
  <label><input type="checkbox" aria-label="已审核患者与就诊信息" disabled={busy||dirty||draft.state==='confirmed'} checked={draft.state==='confirmed'||identityReviewed} onChange={e=>setIdentityReviewed(e.target.checked)}/>已核对患者与就诊信息</label>
  <div className="action-buttons"><button disabled={busy||!dirty} onClick={()=>run(async()=>{apply(await request<Draft>(`/v1/outpatient/drafts/${draft.id}`,body({expected_version:draft.version,document,patient,encounter},'PUT')));setNotice('修改已保存，请重新审核当前版本。')})}>保存修改</button><button className="primary-button" disabled={busy||dirty||checked.length!==keys.length||!identityReviewed||draft.state==='confirmed'} onClick={()=>run(async()=>apply(await request<Draft>(`/v1/outpatient/drafts/${draft.id}/confirm`,body({expected_version:draft.version,reviewed:true,reviewed_sections:checked,patient_encounter_reviewed:identityReviewed}))))}>确认全部病历</button></div>
  {draft.state==='confirmed'&&<><button disabled={busy||dirty} onClick={()=>run(async()=>{
    const saved=await request<Draft>(`/v1/outpatient/drafts/${draft.id}/export`)
    const lines=['门诊病历',`姓名：${saved.patient.name||'未记录'}；患者编号：${saved.patient.patient_id||'未记录'}`,
      `科室：${saved.encounter.department||'未记录'}；就诊时间：${saved.encounter.visited_at||'未记录'}`]
    for(const key of keys){lines.push(SECTIONS[key]);const section=saved.document[key];
      lines.push(section.items.length?section.items.map(item=>`${item.text}${item.assertion==='uncertain'?'（尚不确定）':''}`).join('\n'):'未记录 / 未知')}
    lines.push(`审核医师：${saved.reviewer}；记录版本：${saved.version}`)
    await navigator.clipboard.writeText(lines.join('\n'))
    setNotice('已复制已确认的病历正文，可粘贴到医院系统并再次核对。')
  })}>复制病历正文</button><button disabled={busy||dirty} onClick={()=>run(printRecord)}>打印 / 保存 PDF</button><button disabled={busy||dirty} onClick={()=>run(async()=>{const result=await request<Draft>(`/v1/outpatient/drafts/${draft.id}/export`);const url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));const link=window.document.createElement('a');link.href=url;link.download=`outpatient-${draft.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)})}>下载 JSON（集成用）</button><p>审核医师：{draft.reviewer}</p></>}
  </>:<p>生成后显示九个临床章节和对应原文。</p>}</section></div></>}
  </main></div>
}
