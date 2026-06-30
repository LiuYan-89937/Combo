import { defineConfig, presetUno, presetAttributify, presetIcons } from 'unocss'

export default defineConfig({
  presets: [
    presetUno(),
    presetAttributify(),
    presetIcons({
      scale: 1.2,
      warn: true,
    }),
  ],
  shortcuts: {
    'flex-center': 'flex items-center justify-center',
    'flex-col-center': 'flex flex-col items-center justify-center',
    'absolute-center': 'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
    'transition-base': 'transition-all duration-300 ease-in-out',
  },
  theme: {
    colors: {
      primary: {
        DEFAULT: '#18a058',
        hover: '#36ad6a',
        pressed: '#0c7a43',
      },
      info: {
        DEFAULT: '#2080f0',
        hover: '#4098fc',
        pressed: '#1060c9',
      },
      success: {
        DEFAULT: '#18a058',
        hover: '#36ad6a',
        pressed: '#0c7a43',
      },
      warning: {
        DEFAULT: '#f0a020',
        hover: '#fcb040',
        pressed: '#c97c10',
      },
      error: {
        DEFAULT: '#d03050',
        hover: '#de576d',
        pressed: '#ab1f3f',
      },
    },
  },
})
