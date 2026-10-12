import OutpatientPanel from './OutpatientPanel'
import { LanguageProvider } from './i18n'

export default function App() {
  return <LanguageProvider><OutpatientPanel /></LanguageProvider>
}
