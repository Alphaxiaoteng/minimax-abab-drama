// 流式事件总线：agent 产出的每一步 emit 到 bus，页面订阅后做节流 setData。
// 解耦 agent（生产者）与页面（消费者），并保留完整 steps 以便回放/详情页复用。

function createStreamBus() {
  let steps = [];
  const subs = new Set();
  let finalized = false;

  function emit(event) {
    if (finalized) return;
    if (!event || typeof event.kind !== 'string') return;
    const item = { kind: event.kind, text: event.text === undefined ? '' : String(event.text), at: typeof event.at === 'number' ? event.at : Date.now() };
    steps.push(item);
    for (const cb of subs) {
      try { cb(item); } catch (e) {}
    }
  }

  function on(cb) {
    if (typeof cb !== 'function') return function () {};
    subs.add(cb);
    return function unsubscribe() { subs.delete(cb); };
  }

  function getSteps() { return steps.slice(); }

  function finalize() { finalized = true; }

  function reset() {
    steps = [];
    finalized = false;
  }

  return { emit, on, getSteps, finalize, reset };
}

module.exports = { createStreamBus };