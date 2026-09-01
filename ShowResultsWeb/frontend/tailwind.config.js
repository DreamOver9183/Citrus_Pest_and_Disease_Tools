/** @type {import('tailwindcss').Config} */

// Nocturne design token 的 Tailwind 接線。
//
// 實際色值在 src/styles/nocturne-tokens.css（由 docs/ui_redesign/ 產生），
// 這個檔案只負責把它們接成 utility。採用決策的完整脈絡見
// docs/ui_redesign/adoption-notes.md。
//
// 顏色一律走 `rgb(var(--x-rgb) / <alpha-value>)`，不直接用 var(--x)：
// Tailwind 的透明度修飾詞（bg-accent/10）沒辦法作用在存著完整色值的變數上，
// 必須是空格分隔的通道值配 <alpha-value> 佔位符。前端有 376 處這種寫法。
//
// **CLAUDE.md 硬規則 3 仍然完全適用。** 這個檔案可以用程式產生 token 表
// （Tailwind 在 build 期讀它），但 JSX 裡的 class 字串必須完整靜態出現——
// `bg-cat-${n}-500` 一樣會被 JIT 裁掉。依變數選色請用完整字串的查表物件。
const ch = (name) => `rgb(var(--color-${name}-rgb) / <alpha-value>)`;
const ramp = (role, steps) =>
  Object.fromEntries(steps.map((s) => [String(s), ch(`${role}-${s}`)]));

const FULL = [100, 200, 300, 400, 500, 600, 700, 800, 900];
const SEMANTIC = [300, 500, 700, 900];

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./src/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ground: ch('bg'),
        surface: ch('surface'),
        ink: ch('text'),

        accent: { DEFAULT: ch('accent'), ...ramp('accent', FULL) },

        // Nocturne 的 neutral ramp 刻意用 ds-neutral 而不是覆寫 Tailwind 內建的
        // neutral：目前雖然 0 處在用內建的，覆寫仍是一個看不見的地雷。
        'ds-neutral': ramp('neutral', FULL),

        // 類別色：12 個色相，30° 等距、stride 5 排序使相鄰序列差 150°。
        // 生成參數與 CHART_SERIES / classMap 的對應表見 adoption-notes.md B1。
        cat: Object.fromEntries(
          Array.from({ length: 12 }, (_, i) => [
            String(i + 1),
            { 400: ch(`cat-${i + 1}-400`), 500: ch(`cat-${i + 1}-500`) },
          ])
        ),

        // 語意色只有三個角色。「進行中」刻意不另設 info，直接用 accent。
        success: ramp('success', SEMANTIC),
        warning: ramp('warning', SEMANTIC),
        danger: ramp('danger', SEMANTIC),
      },

      // 這是本階段唯一會改變畫面的一項，而且是修既有的 bug：原本 index.css
      // 匯入的 Outfit 被 font-sans 蓋掉，整個 app 其實用系統字型在跑。
      fontFamily: {
        sans: ['Inter', 'Noto Sans TC', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },

      // 圓角、陰影、間距刻意用 ds- 前綴另開，**不覆寫** Tailwind 既有的尺度：
      // rounded 在原始碼用了 247 處、shadow 97 處，覆寫會讓全站立刻變樣，
      // 而基礎建設層的前提就是不改任何元件外觀。逐頁遷移時再換成 ds- 這組。
      borderRadius: {
        'ds-sm': 'var(--radius-sm)',
        'ds': 'var(--radius-md)',
        'ds-lg': 'var(--radius-lg)',
      },
      boxShadow: {
        'ds-sm': 'var(--shadow-sm)',
        'ds': 'var(--shadow-md)',
        'ds-lg': 'var(--shadow-lg)',
      },
      spacing: {
        'ds-1': 'var(--space-1)',
        'ds-2': 'var(--space-2)',
        'ds-3': 'var(--space-3)',
        'ds-4': 'var(--space-4)',
        'ds-6': 'var(--space-6)',
        'ds-8': 'var(--space-8)',
      },
    },
  },
  plugins: [],
}
