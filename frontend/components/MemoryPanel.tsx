import { useState, useRef, useEffect } from 'react'
import { Disclosure } from '@headlessui/react'
import { ChevronDown, Clock } from 'lucide-react'
import { useToast } from '../hooks/useToast'

interface Insight {
  id: string
  date: string
  content: string
}

interface Fact {
  id: string
  entity: string
  content: string
}

interface RetrievedDoc {
  id: string
  filename: string
  relevance: number
}

interface MemoryData {
  metaRule: string
  lastUpdated: number
  conversationCount: number
  insights: Insight[]
  facts: Fact[]
  retrievedDocs: RetrievedDoc[]
}

interface MemoryPanelProps {
  refreshKey?: number
  userId?: string
  sessionId?: string
}

export default function MemoryPanel({ refreshKey = 0, userId, sessionId }: MemoryPanelProps) {
  const [memoryData, setMemoryData] = useState<MemoryData>({
    metaRule: '你是专业的企业知识助手，回答要准确、简洁、有依据。',
    lastUpdated: Date.now(),
    conversationCount: 5,
    insights: [
      { id: '1', date: '03-02', content: '用户常询问贷款审批流程相关问题' },
      { id: '2', date: '03-01', content: '需要提前准备客户身份信息' },
    ],
    facts: [
      { id: '1', entity: '贷款审批', content: '需要提供身份证、收入证明' },
      { id: '2', entity: '贷款审批', content: '审批周期一般为3-5个工作日' },
      { id: '3', entity: '贷款利率', content: '当前年利率为4.5%' },
    ],
    retrievedDocs: [
      { id: '1', filename: '贷款审批流程.pdf', relevance: 0.95 },
      { id: '2', filename: '员工手册.docx', relevance: 0.82 },
    ],
  })
  const { showToast } = useToast()

  const [highlightLayer, setHighlightLayer] = useState<string | null>(null)
  const prevHashRef = useRef({
    metaRule: '',
    insights: '',
    facts: '',
    retrieved: '',
  })

  useEffect(() => {
    const fetchData = async () => {
      try {
        const params = new URLSearchParams()
        if (userId) params.append('user_id', userId)
        if (sessionId) params.append('session_id', sessionId)
        const queryString = params.toString()
        const response = await fetch(`/api/memory/status${queryString ? '?' + queryString : ''}`)
        if (response.ok) {
          const result = await response.json()
          const data = result.data || result
          
          // 字段名映射：后端下划线命名 -> 前端驼峰命名
          const mappedData: MemoryData = {
            metaRule: data.meta_rule?.content || '你是专业的企业知识助手，回答要准确、简洁、有依据。',
            lastUpdated: data.meta_rule?.updated_at ? new Date(data.meta_rule.updated_at).getTime() : Date.now(),
            conversationCount: data.meta_rule?.conversation_count || 0,
            insights: data.insights || [],
            facts: data.facts || [],
            retrievedDocs: data.retrieved_docs || [],
          }
          
          setMemoryData(mappedData)
        } else {
          throw new Error(`请求失败: ${response.status}`)
        }
      } catch (error) {
        console.error('Fetch memory status error:', error)
        showToast(error instanceof Error ? error.message : '获取记忆数据失败', 'error')
      }
    }
    fetchData()
  }, [refreshKey, showToast])

  useEffect(() => {
    const newHashes = {
      metaRule: memoryData.metaRule,
      insights: JSON.stringify(memoryData.insights || []),
      facts: JSON.stringify(memoryData.facts || []),
      retrieved: JSON.stringify(memoryData.retrievedDocs || []),
    }

    Object.entries(newHashes).forEach(([key, hash]) => {
      if (prevHashRef.current[key as keyof typeof prevHashRef.current] !== hash) {
        setHighlightLayer(key)
        setTimeout(() => setHighlightLayer(null), 800)
      }
    })

    prevHashRef.current = newHashes
  }, [memoryData])

  const getTimeAgo = (timestamp: number) => {
    const minutes = Math.floor((Date.now() - timestamp) / 60000)
    if (minutes < 1) return '刚刚'
    if (minutes < 60) return `${minutes}分钟`
    if (minutes < 1440) return `${Math.floor(minutes / 60)}小时`
    return `${Math.floor(minutes / 1440)}天`
  }

  const factsByEntity = (memoryData.facts || []).reduce((acc, fact) => {
    if (!acc[fact.entity]) {
      acc[fact.entity] = []
    }
    acc[fact.entity].push(fact)
    return acc
  }, {} as Record<string, Fact[]>)

  return (
    <div className="flex flex-col h-full border-t border-gray-200 overflow-hidden">
      <div className="p-3 border-b border-gray-200 bg-gray-50 flex-shrink-0">
        <h2 className="text-base font-semibold text-gray-800">记忆面板</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-thin min-h-0">
        <Disclosure defaultOpen>
          {({ open }) => (
            <div className={`
              bg-white rounded-lg border border-gray-200 overflow-hidden
              ${highlightLayer === 'metaRule' ? 'highlight-animation' : ''}
            `}>
              <Disclosure.Button className="w-full flex items-center justify-between p-4 text-left group" title="语义记忆（角色规则层）">
                <div className="flex items-center gap-3">
                  <div className="w-1 h-8 bg-blue-500 rounded-full" />
                  <div>
                    <h3 className="font-semibold text-gray-800">Layer0 元规则</h3>
                    <div className="flex items-center gap-2 text-xs text-gray-400 mt-1">
                      <Clock size={12} />
                      <span>上次更新 {getTimeAgo(memoryData.lastUpdated)}前</span>
                      <span>·</span>
                      <span>已对话 {memoryData.conversationCount} 轮</span>
                    </div>
                  </div>
                </div>
                <ChevronDown
                  className={`w-5 h-5 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
                />
              </Disclosure.Button>
              <Disclosure.Panel className="px-4 pb-4">
                <p className="text-gray-700 font-medium">
                  {memoryData.metaRule}
                </p>
              </Disclosure.Panel>
            </div>
          )}
        </Disclosure>

        <Disclosure defaultOpen>
          {({ open }) => (
            <div className={`
              bg-white rounded-lg border border-gray-200 overflow-hidden
              ${highlightLayer === 'insights' ? 'highlight-animation' : ''}
            `}>
              <Disclosure.Button className="w-full flex items-center justify-between p-4 text-left group" title="语义记忆（行为模式层）">
                <div className="flex items-center gap-3">
                  <div className="w-1 h-8 bg-purple-500 rounded-full" />
                  <h3 className="font-semibold text-gray-800">Layer1 Insight</h3>
                </div>
                <ChevronDown
                  className={`w-5 h-5 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
                />
              </Disclosure.Button>
              <Disclosure.Panel className="px-4 pb-4">
                {(memoryData.insights || []).length > 0 ? (
                  <div className="space-y-2">
                    {(memoryData.insights || []).slice(0, 5).map((insight) => (
                      <div key={insight.id} className="text-sm text-gray-600">
                        <span className="text-purple-600 font-medium">[{insight.date}]</span>{' '}
                        {insight.content}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400 italic">
                    继续对话，系统将自动提取行为模式
                  </p>
                )}
              </Disclosure.Panel>
            </div>
          )}
        </Disclosure>

        <Disclosure>
          {({ open }) => (
            <div className={`
              bg-white rounded-lg border border-gray-200 overflow-hidden
              ${highlightLayer === 'facts' ? 'highlight-animation' : ''}
            `}>
              <Disclosure.Button className="w-full flex items-center justify-between p-4 text-left group" title="事实记忆（历史结构化事件）">
                <div className="flex items-center gap-3">
                  <div className="w-1 h-8 bg-green-500 rounded-full" />
                  <h3 className="font-semibold text-gray-800">Layer2 事实库</h3>
                </div>
                <ChevronDown
                  className={`w-5 h-5 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
                />
              </Disclosure.Button>
              <Disclosure.Panel className="px-4 pb-4">
                <div className="space-y-2">
                  {Object.entries(factsByEntity).map(([entity, facts]) => (
                    <Disclosure key={entity}>
                      {({ open: entityOpen }) => (
                        <div className="border border-gray-100 rounded-lg">
                          <Disclosure.Button className="w-full flex items-center justify-between p-3 text-left">
                            <span className="text-sm font-medium text-gray-700">
                              {entity} ({facts.length}条)
                            </span>
                            <ChevronDown
                              className={`w-4 h-4 text-gray-400 transition-transform ${entityOpen ? 'rotate-180' : ''}`}
                            />
                          </Disclosure.Button>
                          <Disclosure.Panel className="px-3 pb-3">
                            <ul className="space-y-1">
                              {facts.map((fact) => (
                                <li key={fact.id} className="text-sm text-gray-600 pl-2 border-l-2 border-green-200">
                                  {fact.content}
                                </li>
                              ))}
                            </ul>
                          </Disclosure.Panel>
                        </div>
                      )}
                    </Disclosure>
                  ))}
                </div>
              </Disclosure.Panel>
            </div>
          )}
        </Disclosure>
      </div>
    </div>
  )
}