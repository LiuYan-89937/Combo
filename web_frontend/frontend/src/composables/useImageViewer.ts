import { ref } from 'vue'
import type { LightboxImage } from '@/components/chat/ImageLightbox.vue'

/**
 * 内容图片的统一放大入口。
 *
 * 凡是渲染「内容图片」的地方——消息正文、artifact、工具产物、computer-use
 * 截图、文件预览——都应该通过它打开同一个查看器。这些地方如果各自开新标签
 * 或者干脆不响应点击，用户点到的图片就进不了放大链路。
 *
 * 用法：解构出 ref 直接绑到 `<ImageLightbox>`（顶层 ref 在模板里会自动解包），
 * 点击时调用 `showImage`。
 */
export function useImageViewer() {
  const open = ref(false)
  const index = ref(0)
  const images = ref<LightboxImage[]>([])

  /**
   * 打开查看器。`collection` 是同一组图片（同一段正文、同一批产物），
   * 省略则只放大这一张。返回是否真的打开了——没有 URL 的图片不打开，
   * 调用方据此决定要不要拦掉默认行为。
   */
  function showImage(image: LightboxImage, collection?: LightboxImage[]): boolean {
    const group = (collection?.length ? collection : [image]).filter(entry => Boolean(entry.url))
    const target = group.findIndex(entry => entry.url === image.url)
    if (target < 0) return false
    images.value = group
    index.value = target
    open.value = true
    return true
  }

  return { open, index, images, showImage }
}
