let text = require('fs').readFileSync(require('path').join(__dirname, 'vehicle-burst-matrix.js'), 'utf8')

const witnessAndPlans = `async function openWitness (bot, witness) {
  let block = bot.blockAt(witness)
  if (!block || block.name !== 'barrel') {
    bot.chat(\`/setblock \${witness.x} \${witness.y} \${witness.z} minecraft:barrel[facing=west]\`)
    for (let attempt = 0; attempt < 30; attempt++) {
      await sleep(100)
      block = bot.blockAt(witness)
      if (block && block.name === 'barrel') break
    }
  }
  if (!block || block.name !== 'barrel') {
    return { opened: false, reason: \`missing_after_refresh:\${block ? block.name : 'unloaded'}\` }
  }
  const opened = onceWithTimeout(bot, 'windowOpen', 1600)
  try {
    await bot.lookAt(witness.offset(0.5, 0.5, 0.5), true)
    await bot.activateBlock(block)
  } catch (error) {
    return { opened: false, reason: \`activate:\${error.message}\` }
  }
  if (!await opened) return { opened: false, reason: 'no_window_open' }
  if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  return { opened: true, reason: 'window_open' }
}

function plans () {
  return [
    {
      course: { kind: 'layered', thickness: 16 },
      trials: [[10, true], [20, true], [8, true], [12, true], [16, true]]
    },
    {
      course: { kind: 'layered', thickness: 64 },
      trials: [[10, true], [20, true], [8, true], [12, true], [16, true]]
    },
    {
      course: { kind: 'solid', thickness: 240 },
      trials: [[10, true], [20, true], [8, true], [12, true], [16, true]]
    }
  ]
}

async function runTrial`

text = text.replace(
  /async function openWitness \(bot, witness\) \{[\s\S]*?\n\}\n\nfunction plans \(\) \{[\s\S]*?\n\}\n\nasync function runTrial/,
  witnessAndPlans
)
text = text
  .replaceAll('vehicle-burst-report', 'vehicle-burst-final-report')
  .replaceAll('VehicleBurst', 'VehicleBurstFinal')
  .replaceAll('burst matrix', 'final burst matrix')

eval(text)
