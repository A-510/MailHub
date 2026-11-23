import DOMPurify from 'dompurify'

const SAFE_BITMAP_DATA_URI_RE = /^data:image\/(?:png|jpeg|jpg|gif|webp|bmp);base64,[a-z0-9+/=\s]+$/i

function parsePixelSize(raw: string | null | undefined): number | null {
  if (!raw) return null
  const trimmed = raw.trim().toLowerCase()
  if (!trimmed || trimmed.endsWith('%')) return null
  const match = /^(\d+(?:\.\d+)?)(?:px)?$/.exec(trimmed)
  if (!match) return null
  return Number(match[1])
}

function isTrackingPixel(img: HTMLImageElement): boolean {
  const attrW = parsePixelSize(img.getAttribute('width'))
  const attrH = parsePixelSize(img.getAttribute('height'))
  const styleW = parsePixelSize(img.style.width)
  const styleH = parsePixelSize(img.style.height)
  const width = styleW ?? attrW
  const height = styleH ?? attrH
  return width !== null && height !== null && width <= 2 && height <= 2
}

function createBlockedImageChip(doc: Document, label: string): HTMLSpanElement {
  const chip = doc.createElement('span')
  chip.className = 'blocked-remote-img-chip'
  chip.textContent = label
  return chip
}

/**
 * 清洗邮件 HTML 正文，移除可执行脚本与危险事件，并按隐私配置拦截外部追踪图片。
 */
export function sanitizeEmailHtml(
  rawHtml: string,
  options: { blockRemoteImages: boolean },
): string {
  const clean = DOMPurify.sanitize(rawHtml, {
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'style'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover'],
    ALLOW_DATA_ATTR: false,
  })

  // 统一解析清洗后的 DOM：规范化链接与图片安全属性，并在拦截模式下替换图片为文字标签
  const parser = new DOMParser()
  const doc = parser.parseFromString(clean, 'text/html')

  doc.querySelectorAll('a').forEach((anchor) => {
    anchor.setAttribute('target', '_blank')
    anchor.setAttribute('rel', 'noopener noreferrer')
  })

  doc.querySelectorAll('img').forEach((img) => {
    let src = (img.getAttribute('src') ?? '').trim()
    if (src.startsWith('//')) {
      src = `https:${src}`
      img.setAttribute('src', src)
    }

    // 禁止 SVG 等非安全位图 data URI，避免潜在脚本向量
    if (/^data:/i.test(src) && !SAFE_BITMAP_DATA_URI_RE.test(src)) {
      img.remove()
      return
    }

    const isRemote = /^https?:\/\//i.test(src)
    if (options.blockRemoteImages && isRemote) {
      if (isTrackingPixel(img)) {
        img.remove()
        return
      }
      const altText = (img.getAttribute('alt') ?? '').trim()
      const label = `已拦截外链图片：${altText || '远程图片'}`
      img.replaceWith(createBlockedImageChip(doc, label))
      return
    }

    if (isRemote) {
      // 防止将本地来源 Referer 带往第三方图床导致防盗链 403
      img.setAttribute('referrerpolicy', 'no-referrer')
      img.setAttribute('loading', 'lazy')
    } else if (/^cid:/i.test(src)) {
      img.replaceWith(createBlockedImageChip(doc, '[内嵌图片暂未缓存]'))
    }
  })

  return doc.body.innerHTML
}
