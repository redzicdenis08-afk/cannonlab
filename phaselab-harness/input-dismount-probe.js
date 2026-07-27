'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))
fs.mkdirSync(OUTPUT_DIR, { recursive: true })

function onceWithTimeout (emitter, eventName, timeoutMs) {
  return new Promise(resolve => {
    let settled = false
    const timer = setTimeout(() => finish(null), timeoutMs)
    const handler = (...args) => finish(args)
    function finish (value) {
      if (settled) return
      settled = true
      clearTimeout(timer)
      emitter.removeListener(eventName, handler)
      resolve(value)
    }
    emitter.once(eventName, handler)
  })
}

async function command (bot, text, delay = 100) {
  bot.chat(text)
  await sleep(delay)
}

async function resetAndMount (bot, normalMount) {
  if (bot.vehicle) {
    const event = onceWithTimeout(bot, 'dismount', 900)
    bot.chat('/ride @s dismount')
    await event
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 80)
  const position = onceWithTimeout(bot._client, 'position', 1800)
  bot.chat('/tp @s 0.5 65 0.5')
  await position
  bot.chat('/summon minecraft:oak_boat 0.5 65 0.5 {Rotation:[0f,0f],Invulnerable:1b}')
  await sleep(150)
  const boat = Object.values(bot.entities).find(e => e.name === 'oak_boat' || e.objectType === 'Boat')
  let mountMethod = 'command'
  if (normalMount && boat) {
    const mounted = onceWithTimeout(bot, 'mount', 1200)
    try { bot.mount(boat) } catch (_) {}
    await mounted
    if (bot.vehicle) mountMethod = 'normal'
  }
  if (!bot.vehicle) {
    const mounted = onceWithTimeout(bot, 'mount', 1500)
    bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
    await mounted
  }
  await sleep(150)
  return { mounted: Boolean(bot.vehicle), mountMethod, vehicleId: bot.vehicle?.id ?? null }
}

async function runRawFrames (bot, frames, frameMs = 50) {
  for (const frame of frames) {
    bot._client.write('player_input', { inputs: frame })
    await sleep(frameMs)
  }
}

async function trySequence (bot, plan, id) {
  const mount = await resetAndMount(bot, plan.normalMount)
  await command(bot, `/inputlab start ${id}-${plan.name}`, 60)
  const dismountPromise = onceWithTimeout(bot, 'dismount', 1800)
  let error = null
  try {
    if (plan.kind === 'raw') {
      await runRawFrames(bot, plan.frames, plan.frameMs || 50)
    } else if (plan.kind === 'helper') {
      bot.dismount()
    } else if (plan.kind === 'control') {
      bot.physicsEnabled = true
      bot.setControlState('sneak', true)
      await sleep(plan.holdMs)
      bot.setControlState('sneak', false)
      await sleep(100)
      bot.physicsEnabled = false
    }
  } catch (caught) {
    error = caught.message
  }
  const args = await dismountPromise
  await sleep(250)
  await command(bot, '/inputlab stop', 40)
  return {
    id,
    name: plan.name,
    kind: plan.kind,
    normalMount: plan.normalMount,
    mount,
    error,
    dismountEvent: Boolean(args),
    stillMounted: Boolean(bot.vehicle),
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    }
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'input-dismount-report.json'), JSON.stringify({
    metadata: { generatedAt: new Date().toISOString(), clientVersion: bot.version, serverBrand: bot.game.serverBrand },
    results
  }, null, 2))
  const rows = ['id,name,kind,normal_mount,mount_method,mounted,error,dismount_event,still_mounted,x,y,z']
  for (const r of results) {
    rows.push([
      r.id, r.name, r.kind, r.normalMount, r.mount.mountMethod, r.mount.mounted,
      r.error || '', r.dismountEvent, r.stillMounted,
      r.position.x.toFixed(6), r.position.y.toFixed(6), r.position.z.toFixed(6)
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'input-dismount-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try { if (bot && bot._client && !bot._client.ended) bot.quit('Input probe complete') } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST, port: PORT, username: USERNAME, auth: 'offline', version: '1.21.11',
    physicsEnabled: false, hideErrors: false
  })
  bot.on('kicked', reason => console.error('[InputProbe kicked]', reason))
  bot.on('error', error => console.error('[InputProbe error]', error))
  try {
    if (!await onceWithTimeout(bot, 'spawn', 30000)) throw new Error('Bot did not spawn')
    bot.physicsEnabled = false
    await sleep(800)
    await command(bot, `/gamemode survival ${USERNAME}`)
    await command(bot, '/fill -5 64 -5 5 64 5 minecraft:stone')
    await command(bot, '/fill -5 65 -5 5 70 5 minecraft:air')

    const plans = [
      { name: 'raw_shift_1', kind: 'raw', frames: [{ shift: true }, {}], normalMount: false },
      { name: 'raw_shift_10', kind: 'raw', frames: Array(10).fill({ shift: true }).concat([{}]), normalMount: false },
      { name: 'raw_jump_10', kind: 'raw', frames: Array(10).fill({ jump: true }).concat([{}]), normalMount: false },
      { name: 'raw_shift_jump_10', kind: 'raw', frames: Array(10).fill({ shift: true, jump: true }).concat([{}]), normalMount: false },
      { name: 'mineflayer_dismount', kind: 'helper', normalMount: false },
      { name: 'control_sneak_500', kind: 'control', holdMs: 500, normalMount: false },
      { name: 'raw_shift_10_normal_mount', kind: 'raw', frames: Array(10).fill({ shift: true }).concat([{}]), normalMount: true },
      { name: 'control_sneak_normal_mount', kind: 'control', holdMs: 500, normalMount: true }
    ]

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await trySequence(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[InputProbe] ${result.name} mount=${result.mount.mountMethod}` +
        ` dismount=${result.dismountEvent} stillMounted=${result.stillMounted} error=${result.error || 'none'}`)
    }
    console.log(`[InputProbe] completed=${results.length} dismounted=${results.filter(r => r.dismountEvent).length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[InputProbe fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
