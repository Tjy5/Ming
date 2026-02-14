export const MINISTER_PORTRAIT_FILENAMES: Record<string, string> = {
  魏忠贤: 'wei_zhongxian.png',
  徐光启: 'xu_guangqi.png',
  孙承宗: 'sun_chengzong.png',
  袁崇焕: 'yuan_chonghuan.png',
  周延儒: 'zhou_yanru.png',
  温体仁: 'wen_tiren.png',
  卢象升: 'lu_xiangsheng.png',
  杨嗣昌: 'yang_sichang.png',
}

const PORTRAIT_BASE_PATH = '/portraits'

export function getPortraitFilename(ministerName: string): string {
  return MINISTER_PORTRAIT_FILENAMES[ministerName] ?? `${ministerName}.png`
}

export function getPortraitUrl(ministerName: string): string {
  return `${PORTRAIT_BASE_PATH}/${getPortraitFilename(ministerName)}`
}
