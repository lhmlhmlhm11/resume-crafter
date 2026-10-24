import { fileURLToPath } from 'node:url'
import { FileSystemSkillProvider } from '@deepseek-ai/dsh-skill-filesystem'

export const name = 'resume-crafter'
export const inject = ['skills']

export function apply(ctx) {
  const skillDir = fileURLToPath(new URL('./_staging', import.meta.url))
  ctx.skills.registerProvider((control) =>
    new FileSystemSkillProvider(ctx, control, {
      providerName: 'resume-crafter',
      customSkillDirs: [skillDir],
    }),
  )
}
