const cloud = require('wx-server-sdk')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

const VERSION = '1.0.0'

// 环境连通性探针：不读数据库、不调外部服务、无副作用；供评审与 CI 探测。
exports.main = async () => {
  try {
    return {
      ok: true,
      ts: Date.now(),
      sdk: 'wx-server-sdk',
      version: VERSION
    }
  } catch (err) {
    return {
      ok: false,
      error: { code: 'HEALTH_ERROR', message: (err && err.message) || String(err) }
    }
  }
}