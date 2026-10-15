import { readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
const root = fileURLToPath(new URL('../../src/',import.meta.url))
export async function compileCurveComponent(url: URL, fusionMock?: string): Promise<string> {
  const compiled = compileScript(parse(readFileSync(url,'utf8'), {filename:url.pathname}).descriptor,{id:'curve-component-test',inlineTemplate:true})
  let code = ts.transpileModule(compiled.content,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
    .replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`)
    .replace(/from ['"]@\/([^'"]+)['"]/g,(_match,specifier:string)=>`from '${specifier === 'api/newowFusion' && fusionMock ? fusionMock : pathToFileURL(resolve(root,`${specifier}.ts`)).href}'`)
  for (const match of [...code.matchAll(/from ['"]((?:\.\.\/|\.\/)[^'"]+\.vue)['"]/g)]) {
    code = code.replace(match[0], `from '${await compileCurveComponent(new URL(match[1]!,url),fusionMock)}'`)
  }
  for (const match of [...code.matchAll(/from ['"]((?:\.\.\/|\.\/)[^'"]+)['"]/g)]) {
    const target = new URL(match[1]!.endsWith('.ts') ? match[1]! : `${match[1]}.ts`, url)
    let href = target.href
    const source = readFileSync(target,'utf8')
    if (/import ['"][^'"]+\.css['"]/.test(source)) {
      const module = ts.transpileModule(source.replace(/import ['"][^'"]+\.css['"];?/g,''),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace(/from ['"]vue['"]/g,`from '${import.meta.resolve('vue')}'`)
      href = `data:text/javascript;base64,${Buffer.from(module).toString('base64')}`
    }
    code = code.replace(match[0], `from '${href}'`)
  }
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}
