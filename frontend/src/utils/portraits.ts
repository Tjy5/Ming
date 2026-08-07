// 元末重臣头像文件名映射（图片存放于 public/portraits/，缺失时回退为 `{姓名}.png`）
export const MINISTER_PORTRAIT_FILENAMES: Record<string, string> = {
  徐达: 'xu_da.png',
  常遇春: 'chang_yuchun.png',
  李善长: 'li_shanchang.png',
  刘基: 'liu_ji.png',
  宋濂: 'song_lian.png',
  朱升: 'zhu_sheng.png',
  汤和: 'tang_he.png',
  胡大海: 'hu_dahai.png',
}

const PORTRAIT_BASE_PATH = '/portraits'

export function getPortraitFilename(ministerName: string): string {
  return MINISTER_PORTRAIT_FILENAMES[ministerName] ?? `${ministerName}.png`
}

export function getPortraitUrl(ministerName: string): string {
  return `${PORTRAIT_BASE_PATH}/${getPortraitFilename(ministerName)}`
}
