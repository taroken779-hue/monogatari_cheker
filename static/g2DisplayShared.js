// Shared by the Even Hub Reader and Monogatari Studio's PC preview.
export const G2_BODY_CHARACTER_BUDGET = 108

export function splitDisplayChunks(text, characterBudget) {
  const characters = Array.from(text)
  const budget = Math.max(1, Math.floor(characterBudget))
  const chunks = []
  let offset = 0
  while (offset < characters.length) {
    let end = Math.min(offset + budget, characters.length)
    if (end < characters.length) {
      const minimumBreak = offset + Math.floor(budget * 0.6)
      for (let index = end - 1; index >= minimumBreak; index -= 1) {
        if ('。！？!?、，」』）)'.includes(characters[index] ?? '')) {
          end = index + 1
          break
        }
      }
    }
    chunks.push(characters.slice(offset, end).join(''))
    offset = end
  }
  return chunks.length > 0 ? chunks : ['']
}

export function renderAutoScrolledPageText(timeline, position, characterBudget = G2_BODY_CHARACTER_BUDGET, currentMs = position.sentence.startMs) {
  const page = timeline.pages[position.pageIndex]
  if (!page) return ''
  const budget = Math.max(1, Math.floor(characterBudget))
  const visibleLines = []
  const currentChunks = splitDisplayChunks(position.sentence.text, Math.max(1, budget - 2))
  const currentChunkIndex = displayChunkIndex(position, currentMs, currentChunks.length)
  const currentChunk = currentChunks[currentChunkIndex] ?? ''
  visibleLines.push(`▶ ${currentChunk}`)
  if (currentChunkIndex < currentChunks.length - 1) return visibleLines.join('\n')
  for (let index = position.sentenceIndex + 1; index < page.sentences.length; index += 1) {
    const sentence = page.sentences[index]
    if (!sentence) continue
    const preview = splitDisplayChunks(sentence.text, Math.max(1, budget - 1))[0] ?? ''
    const line = `　${preview}`
    const candidate = [...visibleLines, line].join('\n')
    if (candidate.length > budget) break
    visibleLines.push(line)
  }
  return visibleLines.join('\n')
}

function displayChunkIndex(position, currentMs, chunkCount) {
  if (chunkCount <= 1) return 0
  const duration = Math.max(1, position.sentence.endMs - position.sentence.startMs)
  const progress = Math.min(0.999999, Math.max(0, (currentMs - position.sentence.startMs) / duration))
  return Math.min(chunkCount - 1, Math.floor(progress * chunkCount))
}
