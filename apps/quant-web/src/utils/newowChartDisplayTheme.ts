/** Match the page theme carriers; the workstation's default canvas is light. */
export type NewowChartDisplayTheme = 'light' | 'dark'
export function readNewowChartDisplayTheme(): NewowChartDisplayTheme {
  if(typeof document==='undefined')return 'light'
  const theme=document.body?.getAttribute('data-theme')||document.documentElement?.getAttribute('data-theme')
  return theme?.trim()==='dark'?'dark':'light'
}
