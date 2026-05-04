'use client'

/** Compact timeline of tool calls made by the ToolAgent. Uses only native HTML. */

const TOOL_ICON: Record<string, string> = {
  get_toc:          '🗂',
  get_abstract:     '📝',
  get_references:   '📚',
  get_section_list: '📋',
  read_section:     '📖',
  read_paragraph:   '¶',
  search_text:      '🔍',
  get_lines:        '↔',
  count_stats:      '📊',
  fetch_url:        '🌐',
  finish:           '✓',
}

export type ToolCall = {
  id: string
  tool: string
  args: Record<string, unknown>
  summary: string
  result?: Record<string, unknown>
  error?: string | null
  ts?: number
}

type Props = { calls: ToolCall[] }

export function ToolCallsView({ calls }: Props) {
  if (calls.length === 0) return null
  return (
    <div className="mt-2 rounded border border-zinc-200 bg-zinc-50 text-xs dark:border-zinc-700 dark:bg-zinc-900">
      <div className="border-b border-zinc-200 px-3 py-1.5 font-medium text-zinc-500 dark:border-zinc-700">
        Tool calls ({calls.length})
      </div>
      {calls.map((tc, idx) => (
        <details key={tc.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-800">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 select-none">
            <span className="w-4 shrink-0 text-center">{TOOL_ICON[tc.tool] ?? '⚙'}</span>
            <span className={`shrink-0 font-mono font-medium ${tc.error ? 'text-red-500' : 'text-blue-600 dark:text-blue-400'}`}>
              {tc.tool}
            </span>
            <span className="min-w-0 truncate text-zinc-500">{tc.summary}</span>
            <span className="ml-auto shrink-0 text-zinc-400">▼</span>
          </summary>
          <div className="space-y-1.5 bg-white px-3 pb-2.5 pt-1.5 dark:bg-zinc-900/50">
            {/* Args */}
            {Object.keys(tc.args).length > 0 && (
              <div>
                <p className="mb-0.5 font-semibold text-zinc-400">Args</p>
                <pre className="overflow-x-auto rounded bg-zinc-100 p-1.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {JSON.stringify(tc.args, null, 2)}
                </pre>
              </div>
            )}
            {/* Result */}
            {tc.result && Object.keys(tc.result).length > 0 && (
              <div>
                <p className="mb-0.5 font-semibold text-zinc-400">Output</p>
                <pre className="max-h-48 overflow-auto rounded bg-zinc-100 p-1.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {JSON.stringify(tc.result, null, 2)}
                </pre>
              </div>
            )}
            {tc.error && <p className="text-red-500">Error: {tc.error}</p>}
          </div>
        </details>
      ))}
    </div>
  )
}
