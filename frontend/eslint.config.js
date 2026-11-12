// ESLint flat config:Vue SFC 用 plugin-vue 推荐规则,纯风格规则交给 Prettier。
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import prettierConfig from 'eslint-config-prettier'
import globals from 'globals'

export default [
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  // 必须放在最后:只关掉与 Prettier 冲突的风格规则,不改行为
  prettierConfig,
  {
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
  },
  {
    rules: {
      // eslint-config-prettier v10 没覆盖到这条,但属性行折行同样归 Prettier 管
      'vue/first-attribute-linebreak': 'off',
    },
  },
  {
    files: ['src/App.vue'],
    rules: {
      // 入口组件名是 Vue 项目约定,保持单词名
      'vue/multi-word-component-names': 'off',
    },
  },
  {
    ignores: ['dist/**', 'node_modules/**'],
  },
]
