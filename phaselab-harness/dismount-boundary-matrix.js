'use strict'

const fs = require('fs')
const path = require('path')
const mineflayer = require('mineflayer')
const { Vec3 } = require('vec3')

const HOST = process.env.PHASELAB_HOST || '127.0.0.1'
const PORT = Number(process.env.PHASELAB_PORT || 25565)
const USERNAME = process.env.PHASELAB_USERNAME || 'PhaseBot'
const OUTPUT_DIR = path.resolve(process.env.PHASELAB_OUTPUT || 'output')
const Y = 65
const Z = 0.50
const CLAIM_MIN = 0
const CLAIM_MAX = 15.999
const WITNESS = new Vec3(3, 65, 0)

const POSITIONS = [-1.45, -1.20, -0.95, -0.70, -0.45]
const YAWS = [-90, 90, 0, 180]
const GEOMETRIES = ['open', 'rear_cage', 'roofed_cage', 'water_cage']

fs.mkdirSync(OUTPUT_DIR, { recursive: true })
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

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

async function setupBase (bot) {
  await command(bot, '/gamerule doDaylightCycle false')
  await command(bot, '/time set day')
  await command(bot, `/gamemode survival ${USERNAME}`)
  await command(bot, `/effect give ${USERNAME} minecraft:resistance infinite 255 true`)
  await command(bot, `/effect give ${USERNAME} minecraft:regeneration infinite 255 true`)
  await command(bot, `/claimlab zone ${CLAIM_MIN} ${CLAIM_MAX}`)
  await command(bot, '/claimlab mode likely')
  await command(bot, `/claimlab relation ${USERNAME} enemy`)
  await command(bot, `/dismountlab zone ${CLAIM_MIN} ${CLAIM_MAX}`)
  await command(bot, '/dismountlab mode observe')
}

async function buildGeometry (bot, geometry) {
  await command(bot, '/fill -5 63 -5 6 72 5 minecraft:air', 180)
  await command(bot, '/fill -5 64 -5 6 64 5 minecraft:stone', 140)
  await command(bot, '/fill 0 65 -3 0 69 3 minecraft:obsidian', 120)
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 100)

  if (geometry === 'rear_cage' || geometry === 'roofed_cage' || geometry === 'water_cage') {
    await command(bot, '/fill -3 65 -2 -2 68 2 minecraft:obsidian', 80)
    await command(bot, '/fill -2 65 -2 -1 68 -2 minecraft:obsidian', 80)
    await command(bot, '/fill -2 65 2 -1 68 2 minecraft:obsidian', 80)
  }
  if (geometry === 'roofed_cage' || geometry === 'water_cage') {
    await command(bot, '/fill -2 68 -1 -1 68 1 minecraft:obsidian', 80)
  }
  if (geometry === 'water_cage') {
    await command(bot, '/fill -2 65 -1 -1 67 1 minecraft:water', 120)
  }
}

async function resetPlayerAndBoat (bot) {
  if (bot.vehicle) {
    const dismounted = onceWithTimeout(bot, 'dismount', 800)
    bot.chat('/ride @s dismount')
    await dismounted
  }
  await command(bot, '/kill @e[type=minecraft:oak_boat]', 80)
  const position = onceWithTimeout(bot._client, 'position', 1600)
  bot.chat(`/tp @s -4 ${Y} ${Z}`)
  if (!await position) throw new Error('Reset position packet missing')
  await command(bot, '/claimlab reset', 50)
  await command(bot, '/dismountlab reset', 50)
}

async function mountFixture (bot, x, yaw) {
  bot.chat(`/summon minecraft:oak_boat ${x} ${Y} ${Z} {Rotation:[${yaw}f,0f],Invulnerable:1b}`)
  await sleep(120)
  const mounted = onceWithTimeout(bot, 'mount', 1600)
  bot.chat('/ride @s mount @e[type=minecraft:oak_boat,limit=1,sort=nearest]')
  await mounted
  await sleep(120)
  return bot.vehicle || null
}

async function authoritativeSnapshot (bot) {
  const packetPromise = onceWithTimeout(bot._client, 'position', 1800)
  bot.chat('/tp @s ~ ~ ~')
  const args = await packetPromise
  await sleep(100)
  return {
    packet: args ? args[0] : null,
    position: {
      x: bot.entity.position.x,
      y: bot.entity.position.y,
      z: bot.entity.position.z
    }
  }
}

async function openWitness (bot) {
  await command(bot, `/setblock ${WITNESS.x} ${WITNESS.y} ${WITNESS.z} minecraft:barrel[facing=west]`, 80)
  let block = bot.blockAt(WITNESS)
  for (let attempt = 0; attempt < 12 && (!block || block.name !== 'barrel'); attempt++) {
    await sleep(80)
    block = bot.blockAt(WITNESS)
  }
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: `missing:${block ? block.name : 'unloaded'}` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1200)
  try {
    await bot.lookAt(WITNESS.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: `activate:${error.message}` }
  }
  if (!await opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

async function runTrial (bot, plan, id) {
  await resetPlayerAndBoat(bot)
  await buildGeometry(bot, plan.geometry)
  const boat = await mountFixture(bot, plan.boatX, plan.yaw)
  if (!boat) {
    return {
      ...plan,
      id,
      mounted: false,
      dismounted: false,
      snapshot: { position: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z } },
      inside: false,
      witness: { opened: false, reason: 'mount_failed' },
      verified: false
    }
  }

  const before = {
    player: { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z },
    boat: { x: boat.position.x, y: boat.position.y, z: boat.position.z }
  }

  const dismountedPromise = onceWithTimeout(bot, 'dismount', 2200)
  bot.dismount()
  const dismountArgs = await dismountedPromise
  await sleep(350)
  const snapshot = await authoritativeSnapshot(bot)
  const inside = snapshot.position.x >= 0.05 && snapshot.position.x <= CLAIM_MAX
  const beyondWall = snapshot.position.x >= 0.70
  const witness = beyondWall
    ? await openWitness(bot)
    : { opened: false, reason: 'not_beyond_wall' }

  return {
    ...plan,
    id,
    mounted: true,
    dismounted: Boolean(dismountArgs),
    before,
    snapshot,
    inside,
    beyondWall,
    witness,
    verified: Boolean(dismountArgs) && beyondWall && witness.opened
  }
}

function writeReport (results, bot) {
  fs.writeFileSync(path.join(OUTPUT_DIR, 'dismount-boundary-report.json'), JSON.stringify({
    metadata: {
      generatedAt: new Date().toISOString(),
      clientVersion: bot.version,
      serverBrand: bot.game.serverBrand,
      claim: [CLAIM_MIN, CLAIM_MAX],
      count: results.length
    },
    results
  }, null, 2))

  const rows = ['id,geometry,boat_x,yaw,mounted,dismounted,before_player_x,before_boat_x,post_x,post_y,post_z,inside,beyond_wall,witness,verified']
  for (const result of results) {
    rows.push([
      result.id,
      result.geometry,
      result.boatX,
      result.yaw,
      result.mounted,
      result.dismounted,
      result.before ? result.before.player.x.toFixed(6) : '',
      result.before ? result.before.boat.x.toFixed(6) : '',
      result.snapshot.position.x.toFixed(6),
      result.snapshot.position.y.toFixed(6),
      result.snapshot.position.z.toFixed(6),
      result.inside,
      result.beyondWall,
      result.witness.opened,
      result.verified
    ].join(','))
  }
  fs.writeFileSync(path.join(OUTPUT_DIR, 'dismount-boundary-report.csv'), `${rows.join('\n')}\n`)
}

async function shutdown (bot, code) {
  try {
    if (bot && bot._client && !bot._client.ended) bot.quit('PhaseLab dismount matrix complete')
  } catch (_) {}
  await sleep(250)
  process.exit(code)
}

async function main () {
  const bot = mineflayer.createBot({
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: 'offline',
    version: '1.21.11',
    physicsEnabled: false,
    hideErrors: false
  })
  bot.on('kicked', reason => console.error('[DismountMatrix kicked]', reason))
  bot.on('error', error => console.error('[DismountMatrix error]', error))

  try {
    const spawned = await onceWithTimeout(bot, 'spawn', 30000)
    if (!spawned) throw new Error('Dismount bot did not spawn')
    bot.physicsEnabled = false
    await sleep(900)
    await setupBase(bot)

    const plans = []
    for (const geometry of GEOMETRIES) {
      for (const boatX of POSITIONS) {
        for (const yaw of YAWS) {
          plans.push({ geometry, boatX, yaw })
        }
      }
    }

    const results = []
    for (let id = 0; id < plans.length; id++) {
      const result = await runTrial(bot, plans[id], id)
      results.push(result)
      writeReport(results, bot)
      console.log(`[DismountMatrix] ${id + 1}/${plans.length}` +
        ` geometry=${result.geometry} x=${result.boatX} yaw=${result.yaw}` +
        ` dismounted=${result.dismounted} postX=${result.snapshot.position.x.toFixed(3)}` +
        ` witness=${result.witness.opened} verified=${result.verified}`)
    }

    const verified = results.filter(result => result.verified)
    console.log(`[DismountMatrix] completed=${results.length} verified=${verified.length}`)
    await shutdown(bot, 0)
  } catch (error) {
    console.error('[DismountMatrix fatal]', error)
    await shutdown(bot, 1)
  }
}

main()
