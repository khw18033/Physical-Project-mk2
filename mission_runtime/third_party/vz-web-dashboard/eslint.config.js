// ESLint — 버그 잡는 규칙만 켠다(스타일·미사용 변수·포매팅은 보지 않는다).
// 타입 검사는 `npm run typecheck`(tsc)가 맡고, 여기서는 tsc 가 못 잡는
// 도달 불가 코드·switch fallthrough·Hook 호출 규칙 같은 것만 본다.
// 같은 규칙 묶음이 ../viz-debugger/eslint.config.js 에도 있다 — 바꾸면 둘 다 바꾼다.
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  {
    files: ['**/*.{ts,tsx,js,mjs,cjs,jsx}'],
    languageOptions: {
      parser: tseslint.parser,
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks },
    // 코드에 남아 있는 react-hooks/exhaustive-deps 억제 주석을 "안 쓰는 주석"으로 보고하지 않는다.
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    rules: {
      'no-dupe-keys': 'error',
      'no-duplicate-case': 'error',
      'no-dupe-else-if': 'error',
      'no-unreachable': 'error',
      'no-fallthrough': 'error',
      'no-self-assign': 'error',
      'no-cond-assign': 'error',
      'valid-typeof': 'error',
      'no-unsafe-finally': 'error',
      'use-isnan': 'error',
      'no-constant-condition': 'warn',
      'react-hooks/rules-of-hooks': 'error',
    },
  },
];
