import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    environment: 'node',
    // 确定性：禁止并发写同一临时目录，测试自身保持隔离
    pool: 'threads',
    reporters: ['default'],
  },
});
