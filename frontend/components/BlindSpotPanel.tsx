import { useState, useEffect, useRef } from 'react'
import { RefreshCw, Lightbulb, Pin, Settings, CheckCircle, Upload, FileText, AlertTriangle, BookOpen } from 'lucide-react'
import { useToast } from '../hooks/useToast'

interface BlindSpot {
  id: string
  type: 'knowledge' | 'sop'
  title: string
  queryCount: number
  sampleQueries: string[]
  suggestion: string
}

interface PoorlyAnsweredItem {
  id: string
  query: string
  feedbackType: string
  createdAt: string
}

interface CachedData {
  blindSpots: BlindSpot[]
  poorlyAnswered: PoorlyAnsweredItem[]
  lastAnalyzed: number
  unhitCount?: number
  generatedAt?: string // 后端返回的生成时间
}

interface BlindSpotPanelProps {
  onUploadSop?: () => void
  onUploadKnowledge?: () => void
  cachedData?: CachedData | null
  analyzedAt?: string | null
  onAnalyzeComplete?: (data: CachedData) => void
}

export default function BlindSpotPanel({ 
  onUploadSop, 
  onUploadKnowledge,
  cachedData: propCachedData,
  analyzedAt,
  onAnalyzeComplete
}: BlindSpotPanelProps) {
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [showSopDraftModal, setShowSopDraftModal] = useState(false)
  const [showGapReportModal, setShowGapReportModal] = useState(false)
  const [selectedQuery, setSelectedQuery] = useState<string>('')
  const [sopDraftContent, setSopDraftContent] = useState('')
  const [gapReportContent, setGapReportContent] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const isFetching = useRef(false)
  const { showToast } = useToast()

  // 组件加载时自动获取缓存数据
  useEffect(() => {
    if (!propCachedData) {
      fetchAllData(false)
    }
  }, [propCachedData])

  const fetchAllData = async (force: boolean = false) => {
    // 强制刷新时忽略isFetching状态，避免卡住
    if (isFetching.current && !force) return
    isFetching.current = true
    setIsAnalyzing(true)

    try {
      const [blindSpotsRes, poorlyAnsweredRes] = await Promise.all([
        fetch(`/api/feedback/blind_spots?force_refresh=${force}`),
        fetch('/api/feedback/poorly_answered')
      ])

      let allBlindSpots: BlindSpot[] = []
      let poorlyAnsweredItems: PoorlyAnsweredItem[] = []
      let unhitCount: number | undefined

      let generatedAt: string | undefined
      if (blindSpotsRes.ok) {
        const blindSpotsData = await blindSpotsRes.json()
        const rawBlindSpots: any[] = blindSpotsData.data || []
        generatedAt = blindSpotsData.generated_at
        allBlindSpots = rawBlindSpots.map((spot: any, idx: number) => ({
          id: spot.cluster_id?.toString() || `spot_${idx}`,
          type: spot.type || 'knowledge',
          title: spot.summary || '未知问题',
          queryCount: spot.count || 0,
          sampleQueries: spot.representative_queries || [],
          suggestion: spot.suggestion || '',
        }))
      }

      if (poorlyAnsweredRes.ok) {
        const poorlyAnsweredData = await poorlyAnsweredRes.json()
        const queries: string[] = poorlyAnsweredData.queries || []
        unhitCount = poorlyAnsweredData.unhit_count || 0
        poorlyAnsweredItems = queries.map((q, idx) => ({
          id: `pa_${idx}`,
          query: q,
          feedbackType: 'not_answered',
          createdAt: new Date().toISOString()
        }))
      }

      const newCachedData: CachedData = {
        blindSpots: allBlindSpots,
        poorlyAnswered: poorlyAnsweredItems,
        lastAnalyzed: Date.now(),
        unhitCount,
        // 保存后端返回的生成时间
        generatedAt
      }

      onAnalyzeComplete?.(newCachedData)
    } catch (error) {
      console.error('Fetch data error:', error)
      showToast('获取数据失败', 'error')
    } finally {
      setIsAnalyzing(false)
      isFetching.current = false
    }
  }

  const handleRefresh = () => {
    fetchAllData(true)
  }

  const handleMarkHandled = async (id: string, type: 'sop' | 'knowledge') => {
    setRemovingId(id)
    try {
      const response = await fetch('/api/feedback/mark_handled', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ blind_spot_id: id }),
      })

      if (!response.ok) {
        throw new Error('标记失败')
      }

      setTimeout(() => {
        if (propCachedData) {
          onAnalyzeComplete?.({
            ...propCachedData,
            blindSpots: propCachedData.blindSpots.filter(s => s.id !== id)
          })
        }
        setRemovingId(null)
        showToast('已标记为已处理', 'success')
      }, 300)
    } catch (error) {
      console.error('Mark handled error:', error)
      setRemovingId(null)
      showToast(error instanceof Error ? error.message : '标记失败，请重试', 'error')
    }
  }

  const generateGapReport = async (spot: BlindSpot) => {
    setSelectedQuery(spot.title)
    setGapReportContent('')
    setShowGapReportModal(true)
    setIsGenerating(true)

    try {
      const response = await fetch('/api/feedback/generate_gap_report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: spot.title,
          type: spot.type,
          query_count: spot.queryCount,
          sample_queries: spot.sampleQueries
        }),
      })

      if (!response.ok) throw new Error('生成报告失败')

      const result = await response.json()
      setGapReportContent(result.report || '暂无报告内容')
    } catch (error) {
      console.error('Generate gap report error:', error)
      showToast('生成报告失败', 'error')
      setGapReportContent('生成报告失败，请重试')
    }

    setIsGenerating(false)
  }

  const generateSopDraft = async (query: string) => {
    setSelectedQuery(query)
    setSopDraftContent('')
    setShowSopDraftModal(true)
    setIsGenerating(true)

    try {
      const response = await fetch('/api/feedback/generate_sop_draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })

      if (!response.ok) throw new Error('生成SOP草稿失败')

      const result = await response.json()
      setSopDraftContent(result.draft || '暂无草稿内容')
    } catch (error) {
      console.error('Generate SOP draft error:', error)
      showToast('生成SOP草稿失败', 'error')
      setSopDraftContent('生成草稿失败，请重试')
    }

    setIsGenerating(false)
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      showToast('已复制到剪贴板', 'success')
    })
  }

  const getTimeAgo = (timestamp: number) => {
    const minutes = Math.floor((Date.now() - timestamp) / 60000)
    if (minutes < 1) return '刚刚'
    if (minutes < 60) return `${minutes}分钟`
    return `${Math.floor(minutes / 60)}小时`
  }

  const sopBlindSpots = propCachedData?.blindSpots.filter(s => s.type === 'sop') || []
  const knowledgeBlindSpots = propCachedData?.blindSpots.filter(s => s.type === 'knowledge') || []
  const poorlyAnswered = propCachedData?.poorlyAnswered || []

  return (
    <div className="flex flex-col h-full">
      {/* 头部 */}
      <div className="p-4 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-800">盲区分析</h2>
          <div className="flex items-center gap-3">
            {analyzedAt && propCachedData && (
              <span className="text-sm text-gray-400">
                上次分析：{analyzedAt}
              </span>
            )}
            <button
              onClick={handleRefresh}
              disabled={isAnalyzing}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <RefreshCw size={16} className={isAnalyzing ? 'animate-spin' : ''} />
              重新分析
            </button>
          </div>
        </div>
      </div>

      {/* Loading条 */}
      {isAnalyzing && propCachedData && (
        <div className="p-3 bg-blue-50 border-b border-blue-200">
          <div className="flex items-center gap-2 text-blue-600 text-sm">
            <RefreshCw size={16} className="animate-spin" />
            分析中，请稍候...
          </div>
        </div>
      )}

      {/* 内容区域 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6 scrollbar-thin">
        {/* 空状态 */}
        {!propCachedData ? (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 py-12">
            <RefreshCw size={48} className="mb-4 text-gray-300" />
            <p className="text-lg">点击「重新分析」开始盲区分析</p>
          </div>
        ) : (
          <>
            {/* 第一区：SOP类缺口 */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-1 h-6 bg-orange-500 rounded-full"></div>
                <h3 className="font-semibold text-gray-800">SOP类缺口</h3>
                <span className="text-sm text-gray-500">({sopBlindSpots.length}个)</span>
              </div>
              
              {sopBlindSpots.length === 0 ? (
                <div className="bg-gray-50 rounded-lg p-4 text-center text-gray-500">
                  暂无SOP类缺口
                </div>
              ) : (
                <div className="space-y-3">
                  {sopBlindSpots.map((spot) => (
                    <div
                      key={spot.id}
                      className={`
                        bg-white rounded-lg border-l-4 border-orange-500 shadow-sm overflow-hidden
                        ${removingId === spot.id ? 'opacity-0 scale-y-0' : 'opacity-100'}
                        transition-all duration-300
                      `}
                      style={{ transformOrigin: 'top' }}
                    >
                      <div className="p-4">
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <div className="p-2 bg-orange-100 text-orange-600 rounded-lg">
                              <Settings size={20} />
                            </div>
                            <div>
                              <h4 className="font-semibold text-gray-800">{spot.title}</h4>
                              <p className="text-sm text-gray-500">{spot.queryCount}次查询</p>
                            </div>
                          </div>
                        </div>

                        <div className="mb-3">
                          <p className="text-sm text-gray-600 mb-1">用户常问：</p>
                          <div className="flex flex-wrap gap-2">
                            {(spot.sampleQueries || []).map((query, idx) => (
                              <span key={idx} className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">
                                {query}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div className="flex items-start gap-2 p-3 bg-orange-50 rounded-lg mb-3">
                          <Lightbulb size={18} className="text-orange-500 flex-shrink-0 mt-0.5" />
                          <p className="text-sm text-gray-700">{spot.suggestion || ''}</p>
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => generateGapReport(spot)}
                            className="flex items-center gap-1 px-3 py-1.5 text-sm text-orange-600 bg-orange-100 rounded-lg hover:bg-orange-200 transition-colors"
                          >
                            <FileText size={16} />
                            生成SOP需求说明
                          </button>
                          <button
                            onClick={() => handleMarkHandled(spot.id, 'sop')}
                            className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            <CheckCircle size={16} />
                            标记已处理
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 第二区：知识类缺口 */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-1 h-6 bg-blue-500 rounded-full"></div>
                <h3 className="font-semibold text-gray-800">知识类缺口</h3>
                <span className="text-sm text-gray-500">({knowledgeBlindSpots.length}个)</span>
              </div>
              
              {knowledgeBlindSpots.length === 0 && sopBlindSpots.length === 0 ? (
                <div className="bg-blue-50 rounded-lg p-4 text-center">
                  <span className="text-sm text-blue-600">✅ 近30天所有查询均有知识库覆盖</span>
                </div>
              ) : knowledgeBlindSpots.length === 0 ? null : (
                <div className="space-y-3">
                  {knowledgeBlindSpots.map((spot) => (
                    <div
                      key={spot.id}
                      className={`
                        bg-white rounded-lg border-l-4 border-blue-500 shadow-sm overflow-hidden
                        ${removingId === spot.id ? 'opacity-0 scale-y-0' : 'opacity-100'}
                        transition-all duration-300
                      `}
                      style={{ transformOrigin: 'top' }}
                    >
                      <div className="p-4">
                        <div className="flex items-start justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <div className="p-2 bg-blue-100 text-blue-600 rounded-lg">
                              <Pin size={20} />
                            </div>
                            <div>
                              <h4 className="font-semibold text-gray-800">{spot.title}</h4>
                              <p className="text-sm text-gray-500">{spot.queryCount}次查询</p>
                            </div>
                          </div>
                        </div>

                        <div className="mb-3">
                          <p className="text-sm text-gray-600 mb-1">用户常问：</p>
                          <div className="flex flex-wrap gap-2">
                            {(spot.sampleQueries || []).map((query, idx) => (
                              <span key={idx} className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded">
                                {query}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div className="flex items-start gap-2 p-3 bg-blue-50 rounded-lg mb-3">
                          <Lightbulb size={18} className="text-blue-500 flex-shrink-0 mt-0.5" />
                          <p className="text-sm text-gray-700">{spot.suggestion || ''}</p>
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => onUploadKnowledge?.()}
                            className="flex items-center gap-1 px-3 py-1.5 text-sm text-blue-600 bg-blue-100 rounded-lg hover:bg-blue-200 transition-colors"
                          >
                            <Upload size={16} />
                            去上传知识文档
                          </button>
                          <button
                            onClick={() => handleMarkHandled(spot.id, 'knowledge')}
                            className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            <CheckCircle size={16} />
                            标记已处理
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 第三区：命中但没答好 */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-1 h-6 bg-gray-400 rounded-full"></div>
                <h3 className="font-semibold text-gray-800">命中但没答好</h3>
                <span className="text-sm text-gray-500">({poorlyAnswered.length}个)</span>
              </div>
              
              {poorlyAnswered.length === 0 ? (
                <div className="bg-gray-50 rounded-lg p-4 text-center text-gray-500">
                  暂无数据
                </div>
              ) : (
                <div className="space-y-3">
                  {poorlyAnswered.map((item) => (
                  <div
                    key={item.id}
                    className="bg-white rounded-lg border-l-4 border-gray-400 shadow-sm p-4"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <div className="p-2 bg-gray-100 text-gray-600 rounded-lg">
                          <AlertTriangle size={20} />
                        </div>
                        <div>
                          <p className="text-gray-800 font-medium">{item.query}</p>
                          <p className="text-xs text-gray-500">
                            {new Date(item.createdAt).toLocaleDateString('zh-CN')}
                          </p>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => generateSopDraft(item.query)}
                      className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                    >
                      <BookOpen size={16} />
                      生成SOP草稿
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>

    {/* SOP草稿Modal */}
    {showSopDraftModal && (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold">
              SOP草稿 - {selectedQuery}
            </h3>
            <button
              onClick={() => setShowSopDraftModal(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>
          <div className="p-4 overflow-auto max-h-[50vh]">
            {isGenerating ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                <span className="ml-3 text-gray-600">AI正在生成SOP草稿...</span>
              </div>
            ) : (
              <div className="prose max-w-none">
                <pre className="whitespace-pre-wrap text-sm text-gray-700 bg-gray-50 p-4 rounded-lg">
                  {sopDraftContent}
                </pre>
              </div>
            )}
          </div>
          <div className="p-4 border-t border-gray-200 flex items-center justify-end gap-2">
            <button
              onClick={() => setShowSopDraftModal(false)}
              className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={() => copyToClipboard(sopDraftContent)}
              disabled={!sopDraftContent || isGenerating}
              className="px-4 py-2 text-blue-600 bg-blue-100 hover:bg-blue-200 rounded-lg transition-colors disabled:opacity-50"
            >
              复制
            </button>
            <button
              onClick={() => {
                showToast('SOP发布功能开发中', 'info')
              }}
              disabled={!sopDraftContent || isGenerating}
              className="px-4 py-2 text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-50"
            >
              确认发布为SOP
            </button>
          </div>
        </div>
      </div>
    )}

    {/* 需求报告Modal */}
    {showGapReportModal && (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
        <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold">
              SOP需求说明 - {selectedQuery}
            </h3>
            <button
              onClick={() => setShowGapReportModal(false)}
              className="text-gray-400 hover:text-gray-600"
            >
              ✕
            </button>
          </div>
          <div className="p-4 overflow-auto max-h-[50vh]">
            {isGenerating ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-orange-600"></div>
                <span className="ml-3 text-gray-600">AI正在生成需求说明...</span>
              </div>
            ) : (
              <div className="prose max-w-none">
                <pre className="whitespace-pre-wrap text-sm text-gray-700 bg-gray-50 p-4 rounded-lg">
                  {gapReportContent}
                </pre>
              </div>
            )}
          </div>
          <div className="p-4 border-t border-gray-200 flex items-center justify-end gap-2">
            <button
              onClick={() => setShowGapReportModal(false)}
              className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              取消
            </button>
            <button
              onClick={() => copyToClipboard(gapReportContent)}
              disabled={!gapReportContent || isGenerating}
              className="px-4 py-2 text-orange-600 bg-orange-100 hover:bg-orange-200 rounded-lg transition-colors disabled:opacity-50"
            >
              复制
            </button>
            <button
              onClick={() => {
                setShowGapReportModal(false)
                onUploadSop?.()
              }}
              disabled={!gapReportContent || isGenerating}
              className="px-4 py-2 text-white bg-orange-600 hover:bg-orange-700 rounded-lg transition-colors disabled:opacity-50"
            >
              去上传SOP
            </button>
          </div>
        </div>
      </div>
    )}
  </div>
  )
}