import { useState } from 'react'
import LegacyApp from './LegacyApp'
import OutpatientPanel from './OutpatientPanel'
export default function App() {
  const [legacy, setLegacy] = useState(false)
  return <><nav style={{padding:12}}><button onClick={()=>setLegacy(!legacy)}>{legacy?'门诊病历（新版本）':'旧版六字段 / 历史记录'}</button></nav>{legacy?<LegacyApp/>:<OutpatientPanel/>}</>
}
