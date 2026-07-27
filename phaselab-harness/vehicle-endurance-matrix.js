let text = require('fs').readFileSync(require('path').join(__dirname, 'vehicle-hardening-matrix.js'), 'utf8')

const focusedPlan = `function trialPlan () {
  return [
    { course: { kind: 'solid', thickness: 240 }, variants: [
      [0.25, 0], [0.25, 2], [0.25, 5], [0.25, 10]
    ] },
    { course: { kind: 'layered', thickness: 16 }, variants: [
      [0.25, 0], [0.25, 2], [0.25, 5], [0.25, 10], [0.25, 20], [0.25, 30], [0.25, 40], [0.25, 50]
    ] },
    { course: { kind: 'layered', thickness: 64 }, variants: [
      [0.25, 0], [0.25, 2], [0.25, 5], [0.25, 10]
    ] }
  ]
}

async function runTrial`

text = text.replace(
  /function trialPlan \(\) \{[\s\S]*?\n\}\n\nasync function runTrial/,
  focusedPlan
)
text = text
  .replaceAll('vehicle-hardening-report', 'vehicle-endurance-report')
  .replaceAll('VehicleHardening', 'VehicleEndurance')
  .replaceAll('vehicle hardening', 'vehicle endurance')
  .replace(
    'results.push(result)\n        const first = result.corrections[0]',
    'results.push(result)\n        writeReports(results, bot)\n        const first = result.corrections[0]'
  )

eval(text)
