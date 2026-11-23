import { getOptionalOnboardingAsset } from '@/utils/optionalAssets'

const mascotPointDown = getOptionalOnboardingAsset('mascot-point-down.png')
const mascotPointRight = getOptionalOnboardingAsset('mascot-point-right.png')
const mascotWelcome = getOptionalOnboardingAsset('mascot-welcome.png')
const arrowComicRight = getOptionalOnboardingAsset('arrow-comic-right.png')
const arrowCurveLeft = getOptionalOnboardingAsset('arrow-curve-left.png')
const arrowCurveRight = getOptionalOnboardingAsset('arrow-curve-right.png')
const arrowDownBold = getOptionalOnboardingAsset('arrow-down-bold.png')
const arrowSpiralRight = getOptionalOnboardingAsset('arrow-spiral-right.png')
const arrowSwirlUpRight = getOptionalOnboardingAsset('arrow-swirl-up-right.png')
const arrowUpBold = getOptionalOnboardingAsset('arrow-up-bold.png')
const cursorClick = getOptionalOnboardingAsset('cursor-click.png')

export const DIRECTIONAL_ARROWS = {
  down: arrowDownBold,
  up: arrowUpBold,
  left: arrowCurveLeft,
  right: arrowCurveRight,
  comicRight: arrowComicRight,
  swirlUpRight: arrowSwirlUpRight,
  spiralRight: arrowSpiralRight,
} as const

/**
 * 新手引导单步配置接口
 */
export interface OnboardingStepConfig {
  /** 步骤唯一标识 */
  id: string
  /** 引导标题 */
  title: string
  /** 引导说明文案 */
  description: string
  /** 关键操作提示要点 */
  tips: string[]
  /** 需要聚光灯高亮的 DOM 选择器；缺省为居中卡片展示 */
  targetSelector?: string
  /** 若存在该选择器，则将点击手势指针贴在其右下角 */
  clickCursorSelector?: string
  /** 是否需要先打开设置弹窗的邮箱渠道页 */
  requiresSettingsAccounts?: boolean
  /** 向导吉祥物贴纸资源 */
  mascotSrc: string
  /** 向导吉祥物定位风格 */
  mascotPlacement: 'top-left' | 'top-right' | 'inline-top'
  /** 梦幻箭头贴纸资源 */
  arrowSrc: string
  /** 梦幻箭头目标相对方位（用于定位箭头位置） */
  arrowPlacement: 'to-right' | 'to-up' | 'to-left' | 'to-top-right' | 'decor-cta'
  /** 引导卡片相对于目标元素的首选方位 */
  preferredSide: 'center' | 'left' | 'bottom' | 'right' | 'top'
  /** 聚光灯外扩内边距（px） */
  spotlightPadding: number
  /** 主按钮文案 */
  primaryLabel: string
  /** 次级快捷动作按钮文案（可选） */
  secondaryActionLabel?: string
  /** 次级快捷动作类型 */
  secondaryActionKind?: 'stay-in-accounts' | 'open-accounts'
}

export interface RectBox {
  left: number
  top: number
  width: number
  height: number
}

export const ONBOARDING_STEPS: OnboardingStepConfig[] = [
  {
    id: 'welcome',
    title: '欢迎来到 MailHub 樱花书房',
    description:
      '初次见面！我是你的邮件小向导。接下来用 1 分钟带你熟悉书房，并手把手教你绑定自己的真实邮箱。',
    tips: [
      '书桌已内置 5 个示例邮箱与精选邮件，方便先翻阅体验',
      '支持 QQ、163、Gmail、Outlook、iCloud 及学校/企业邮箱',
      '密码与授权码均通过 Fernet 在本地加密存储，安心可靠',
    ],
    mascotSrc: mascotWelcome,
    mascotPlacement: 'top-left',
    arrowSrc: arrowSpiralRight,
    arrowPlacement: 'decor-cta',
    preferredSide: 'center',
    spotlightPadding: 0,
    primaryLabel: '开始向导之旅',
  },
  {
    id: 'open-add-account',
    title: '找到「添加邮箱」入口',
    description:
      '点击右侧「我的邮箱」卡片右上角的「+」号，或底部的「添加邮箱渠道」，即可打开绑定页面接入你的个人邮箱。',
    tips: [
      '勾选多个邮箱前面的复选框，可合并至「全部聚合邮箱」一站阅读',
      '点击任意单个邮箱行，即可像翻书一样切换为独立视角',
    ],
    targetSelector: '[data-tour="account-panel"]',
    clickCursorSelector: '[data-tour="add-account-btn"]',
    requiresSettingsAccounts: false,
    mascotSrc: mascotPointRight,
    mascotPlacement: 'top-right',
    arrowSrc: arrowCurveRight,
    arrowPlacement: 'to-right',
    preferredSide: 'left',
    spotlightPadding: 10,
    primaryLabel: '打开添加邮箱面板',
  },
  {
    id: 'choose-provider',
    title: '选择邮箱服务商与授权指引',
    description:
      '在设置弹窗顶部点击 QQ、163、Gmail、Outlook 等快捷标签，系统会自动填入对应的 IMAP / SMTP 服务器和端口。',
    tips: [
      '紫底指引条内附带「前往官方获取授权」直达链接，照着做只需几十秒',
      '使用学校或企业邮箱时，选择「自定义 IMAP」即可填写专属服务器',
    ],
    targetSelector: '[data-tour="provider-presets"]',
    requiresSettingsAccounts: true,
    mascotSrc: mascotPointDown,
    mascotPlacement: 'inline-top',
    arrowSrc: arrowUpBold,
    arrowPlacement: 'to-up',
    preferredSide: 'bottom',
    spotlightPadding: 10,
    primaryLabel: '下一步：填写授权',
  },
  {
    id: 'fill-credentials',
    title: '填入授权码或浏览器授权登录',
    description:
      'QQ / 163 / 126 / Gmail 请填写邮箱网页端生成的「客户端授权码 / 应用专用密码」（非邮箱登录密码）；Outlook 请切换右上角「跳转浏览器登录」。',
    tips: [
      '填好后先点「测试 IMAP/SMTP 连接」确认通道畅通',
      '点击「验证并添加邮箱」将立即保存并自动同步第一批邮件',
    ],
    targetSelector: '[data-tour="account-auth-area"]',
    requiresSettingsAccounts: true,
    mascotSrc: mascotPointRight,
    mascotPlacement: 'top-right',
    arrowSrc: arrowComicRight,
    arrowPlacement: 'to-right',
    preferredSide: 'left',
    spotlightPadding: 10,
    primaryLabel: '下一步：日常收发',
    secondaryActionLabel: '留在这里立即添加',
    secondaryActionKind: 'stay-in-accounts',
  },
  {
    id: 'sync-and-compose',
    title: '同步刷新与快捷写邮件',
    description:
      '绑定完成后回到主书房，点击这里即可手动同步最新邮件或撰写出彩的新信件；支持定时同步与发信延迟撤回。',
    tips: [
      '左侧书签栏支持收件箱、未读、星标及自动分类标签过滤',
      '常用快捷键：C 键写邮件，J / K 键切换邮件，S 键加星标',
    ],
    targetSelector: '[data-tour="mail-list-actions"]',
    requiresSettingsAccounts: false,
    mascotSrc: mascotPointDown,
    mascotPlacement: 'inline-top',
    arrowSrc: arrowCurveLeft,
    arrowPlacement: 'to-left',
    preferredSide: 'right',
    spotlightPadding: 12,
    primaryLabel: '最后一步',
  },
  {
    id: 'theme-and-replay',
    title: '主题切换与随时重温引导',
    description:
      '右上角悬浮胶囊可随时切换「明亮樱花 / 暗黑星夜」双主题、查看同步日志；点击新增的「?」小图标还能随时把我呼唤回来！',
    tips: [
      '想清理示例邮件？前往「设置中心 → 隐私与数据」即可一键清空演示账号',
    ],
    targetSelector: '[data-tour="topbar-actions"]',
    requiresSettingsAccounts: false,
    mascotSrc: mascotWelcome,
    mascotPlacement: 'top-left',
    arrowSrc: arrowSwirlUpRight,
    arrowPlacement: 'to-top-right',
    preferredSide: 'bottom',
    spotlightPadding: 10,
    primaryLabel: '完成引导，开始使用',
    secondaryActionLabel: '立即去添加邮箱',
    secondaryActionKind: 'open-accounts',
  },
]

export const CLICK_CURSOR_SRC = cursorClick

/**
 * 计算两个矩形的重叠面积，用于防遮挡方位选优
 */
function overlapArea(a: RectBox, b: RectBox): number {
  const xOverlap = Math.max(0, Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left))
  const yOverlap = Math.max(0, Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top))
  return xOverlap * yOverlap
}

/**
 * 将引导卡片矩形钳制在当前视口安全区之内
 */
function clampToViewport(
  left: number,
  top: number,
  width: number,
  height: number,
  vw: number,
  vh: number,
  sideMargin = 16,
  topMargin = 16,
): RectBox {
  const safeLeft = Math.min(Math.max(sideMargin, left), Math.max(sideMargin, vw - width - sideMargin))
  const safeTop = Math.min(Math.max(topMargin, top), Math.max(topMargin, vh - height - sideMargin))
  return { left: safeLeft, top: safeTop, width, height }
}

/**
 * 根据目标高亮矩形与首选方位，智能计算引导卡片最不遮挡目标区域的坐标
 */
export function computeCardRect(
  target: RectBox | null,
  preferred: OnboardingStepConfig['preferredSide'],
  cardWidth: number,
  cardHeight: number,
  vw: number,
  vh: number,
  topMargin = 16,
): { rect: RectBox; actualSide: OnboardingStepConfig['preferredSide'] } {
  if (!target || preferred === 'center') {
    return {
      rect: clampToViewport(
        (vw - cardWidth) / 2,
        (vh - cardHeight) / 2 + 16,
        cardWidth,
        cardHeight,
        vw,
        vh,
        16,
        topMargin,
      ),
      actualSide: 'center',
    }
  }

  const gapX = 52
  const gapY = 58
  const candidatesOrder: Array<Exclude<OnboardingStepConfig['preferredSide'], 'center'>> = [
    preferred,
    ...(['left', 'bottom', 'right', 'top'] as const).filter((s) => s !== preferred),
  ]

  let bestBox: RectBox | null = null
  let bestSide: OnboardingStepConfig['preferredSide'] = preferred
  let bestPenalty = Number.POSITIVE_INFINITY

  for (let i = 0; i < candidatesOrder.length; i++) {
    const side = candidatesOrder[i]
    let rawLeft = 0
    let rawTop = 0

    if (side === 'left') {
      rawLeft = target.left - cardWidth - gapX
      rawTop = target.top + target.height / 2 - cardHeight / 2
    } else if (side === 'right') {
      rawLeft = target.left + target.width + gapX
      rawTop = target.top + target.height / 2 - cardHeight / 2
    } else if (side === 'bottom') {
      rawLeft = target.left + target.width / 2 - cardWidth / 2
      rawTop = target.top + target.height + gapY
    } else {
      rawLeft = target.left + target.width / 2 - cardWidth / 2
      rawTop = target.top - cardHeight - gapY
    }

    // top 方向放置时允许更小顶部边距以免硬挤到下方目标区域上；最终在组件中自动降级为 inline-top
    const effTopMargin = side === 'top' ? 16 : topMargin
    const clamped = clampToViewport(rawLeft, rawTop, cardWidth, cardHeight, vw, vh, 16, effTopMargin)
    const overlap = overlapArea(clamped, target)
    // 首选方位在零遮挡时占优势；若存在遮挡按遮挡面积重罚
    const penalty = overlap * 20 + i * 28

    if (penalty < bestPenalty) {
      bestPenalty = penalty
      bestBox = clamped
      bestSide = side
    }
    if (overlap === 0 && i === 0) {
      break
    }
  }

  return {
    rect: bestBox ?? clampToViewport((vw - cardWidth) / 2, (vh - cardHeight) / 2, cardWidth, cardHeight, vw, vh),
    actualSide: bestSide,
  }
}
