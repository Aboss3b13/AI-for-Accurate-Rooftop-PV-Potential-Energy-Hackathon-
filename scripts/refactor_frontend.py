"""One-time component extraction utility used during initial implementation."""
from pathlib import Path

path=Path('frontend/src/App.tsx')
text=path.read_text(encoding='utf-8')
start=text.index('          <aside>')
end=text.index('          </aside>',start)+len('          </aside>')
jsx=text[start:end].replace('busy || !file || roof.length < 3','busy || !ready')
header='''import { Sun, Zap, ScanLine, AlertCircle, LoaderCircle, ArrowUpRight, Download } from "lucide-react";
import type {Analysis, Mode} from '../types';
type Props = {result:Analysis|null;busy:boolean;ready:boolean;mode:Mode;setMode:(mode:Mode)=>void;error:string;analyse:()=>Promise<void>;exportJson:()=>void;model:string;comparisons:Partial<Record<Mode,number>>};
const MODES:Mode[]=['conservative','recommended','maximum'];
export default function AnalysisPanel({result,busy,ready,mode,setMode,error,analyse,exportJson,model,comparisons}:Props){
const stats=result?.statistics;
return (
'''
Path('frontend/src/components/AnalysisPanel.tsx').write_text(header+jsx+'\n);\n}\n',encoding='utf-8')
text=text[:start]+'''          <AnalysisPanel result={result} busy={busy} ready={!!file && roof.length >= 3} mode={mode} setMode={setMode} error={error} analyse={analyse} exportJson={exportJson} model={model} comparisons={comparisons}/>'''+text[end:]
text='import AnalysisPanel from "./components/AnalysisPanel";\n'+text
text=text.replace('  Download,\n','').replace('  AlertCircle,\n','').replace('  Zap,\n','')
text=text.replace('const MODES: Mode[] = ["conservative", "recommended", "maximum"];\n','')
path.write_text(text,encoding='utf-8')
