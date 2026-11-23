const rootOptionalAssets = import.meta.glob<string>('../assets/*.png', {
  eager: true,
  import: 'default',
})

const onboardingOptionalAssets = import.meta.glob<string>('../assets/onboarding/*.png', {
  eager: true,
  import: 'default',
})

/**
 * 获取可选的内置背景或立绘图片资源 URL；当开源仓库未包含本地图片素材时安全回退为空字符串。
 * @param filename 位于 src/assets/ 下的图片文件名
 * @returns 构建解析后的资源 URL，缺失时返回空字符串
 */
export function getOptionalAsset(filename: string): string {
  return rootOptionalAssets[`../assets/${filename}`] ?? ''
}

/**
 * 获取可选的新手向导贴纸图片资源 URL；当未包含本地贴纸素材时安全回退为空字符串。
 * @param filename 位于 src/assets/onboarding/ 下的贴纸文件名
 * @returns 构建解析后的资源 URL，缺失时返回空字符串
 */
export function getOptionalOnboardingAsset(filename: string): string {
  return onboardingOptionalAssets[`../assets/onboarding/${filename}`] ?? ''
}
