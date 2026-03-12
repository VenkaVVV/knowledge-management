import { useState, useEffect, useRef } from 'react'
import { CheckCircle, AlertTriangle, XCircle, History, Brain } from 'lucide-react'
import { useToast } from '../hooks/useToast'

interface SopItem {
  id: number
  process_name: string
  filename: string
  applicable_role: string
  last_verified: string
  verify_count: number
  version: string
  status: string
  uploaded_at: string
  needs_review: boolean
  days_since_verified: number
  health: 'good' | 'warning' | 'overdue'
}

interface StalenessResult {
  sop_id: number
  process_name: string
  risk: 'high' | 'medium' | 'low'
  reason: string
  suggestion: string
  related_files: string[]
}

export default function SOPPanel() {
  const [sopList, setSopList] = useState<SopItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showHistoryModal, setShowHistoryModal] = useState(false)
  const [showStalenessModal, setShowStalenessModal] = useState(false)
  const [selectedSop, setSelectedSop] = useState<SopItem | null>(null)
  const [historySops, setHistorySops] = useState<SopItem[]>([])
  const [stalenessResult, setStalenessResult] = useState<StalenessResult | null>(null)
  const isFetching = useRef(false)
  const { showToast } = useToast()

  // 统计数据
  const stats = {
    good: sopList.filter(s => s.health === 'good').length,
    warning: sopList.filter(s => s.health === 'warning').length,
    overdue: sopList.filter(s => s.health === 'overdue').length,
  }

  useEffect(() => {
    if (isFetching.current) return
    isFetching.current = true
    
    fetchSopList()
  }, [])

  const fetchSopList = async () => {
    try {
      setLoading(true)
      const response = await fetch('/api/feedback/sop_list')
      if (!response.ok) throw new Error('获取SOP列表失败')
      const result = await response.json()
      if (result.data) {
        setSopList(result.data)
      }
    } catch (error) {
      console.error('Fetch SOP list error:', error)
      showToast('获取SOP列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (sopId: number, action: 'confirm' | 'update') => {
    try {
      const response = await fetch('/api/feedback/verify_sop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sop_id: sopId, action }),
      })
      if (!response.ok) throw new Error('核验操作失败')
      showToast(action === 'confirm' ? 'SOP核验确认成功' : 'SOP更新状态已标记', 'success')
      fetchSopList()
    } catch (error) {
      console.error('Verify SOP error:', error)
      showToast('核验操作失败', 'error')
    }
  }

  const openHistoryModal = async (sop: SopItem) => {
    setSelectedSop(sop)
    // 查找同名SOP的所有版本
    const history = sopList.filter(s => s.process_name === sop.process_name)
    setHistorySops(history)
    setShowHistoryModal(true)
  }

  const checkStaleness = async (sop: SopItem) => {
    setSelectedSop(sop)
    setStalenessResult(null)
    setShowStalenessModal(true)
    
    try {
      const response = await fetch('/api/feedback/check_sop_staleness', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sop_id: sop.id }),
      })
      if (!response.ok) throw new Error('AI比对失败')
      const result = await response.json()
      if (result.data) {
        setStalenessResult(result.data)
      } else {
        throw new Error('返回数据格式错误')
      }
    } catch (error) {
      console.error('Check staleness error:', error)
      showToast('AI比对失败: ' + (error instanceof Error ? error.message : '未知错误'), 'error')
    }
  }

  const getHealthBadge = (health: string) => {
    switch (health) {
      case 'good':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-100 text-green-700 rounded-full text-xs">
            <CheckCircle size={12} />
            正常
          </span>
        )
      case 'warning':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-yellow-100 text-yellow-700 rounded-full text-xs">
            <AlertTriangle size={12} />
            待核验
          </span>
        )
      case 'overdue':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-1 bg-red-100 text-red-700 rounded-full text-xs">
            <XCircle size={12} />
            严重过期
          </span>
        )
      default:
        return null
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* 统计区域 */}
      <div className="p-4 border-b border-gray-200 bg-gray-50">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 px-3 py-1.5 bg-green-100 text-green-700 rounded-full text-sm">
              <CheckCircle size={14} />
              正常 {stats.good}个
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 px-3 py-1.5 bg-yellow-100 text-yellow-700 rounded-full text-sm">
              <AlertTriangle size={14} />
              待核验 {stats.warning}个
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1 px-3 py-1.5 bg-red-100 text-red-700 rounded-full text-sm">
              <XCircle size={14} />
              严重过期 {stats.overdue}个
            </span>
          </div>
        </div>
      </div>

      {/* SOP列表 */}
      <div className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            加载中...
          </div>
        ) : sopList.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-500">
            暂无SOP数据
          </div>
        ) : (
          <div className="space-y-3">
            {sopList.map((sop) => (
              <div
                key={sop.id}
                className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <h4 className="font-semibold text-gray-800">{sop.process_name}</h4>
                    <p className="text-sm text-gray-500">
                      版本 {sop.version} | 适用岗位: {sop.applicable_role || '未指定'}
                    </p>
                  </div>
                  {getHealthBadge(sop.health)}
                </div>

                <div className="text-xs text-gray-400 mb-3">
                  最后核验: {sop.last_verified || '未核验'} | 核验次数: {sop.verify_count}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleVerify(sop.id, 'confirm')}
                    className="px-3 py-1.5 bg-blue-100 text-blue-700 rounded-md text-sm hover:bg-blue-200 transition-colors"
                    disabled={sop.health === 'good'}
                  >
                    核验确认
                  </button>
                  <button
                    onClick={() => openHistoryModal(sop)}
                    className="px-3 py-1.5 bg-gray-100 text-gray-700 rounded-md text-sm hover:bg-gray-200 transition-colors flex items-center gap-1"
                  >
                    <History size={14} />
                    版本历史
                  </button>
                  <button
                    onClick={() => checkStaleness(sop)}
                    className="px-3 py-1.5 bg-purple-100 text-purple-700 rounded-md text-sm hover:bg-purple-200 transition-colors flex items-center gap-1"
                  >
                    <Brain size={14} />
                    AI比对风险
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 历史版本Modal */}
      {showHistoryModal && selectedSop && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
            <div className="p-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                {selectedSop.process_name} - 版本历史
              </h3>
              <button
                onClick={() => setShowHistoryModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <div className="p-4 overflow-auto">
              {historySops.length === 0 ? (
                <p className="text-gray-500 text-center py-8">暂无历史版本</p>
              ) : (
                <div className="space-y-3">
                  {historySops
                    .sort((a, b) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime())
                    .map((sop) => (
                      <div
                        key={sop.id}
                        className={`p-3 rounded-lg border ${
                          sop.status === 'latest'
                            ? 'border-blue-200 bg-blue-50'
                            : 'border-gray-200 bg-gray-50'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-medium">版本 {sop.version}</span>
                            {sop.status === 'latest' && (
                              <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">
                                当前版本
                              </span>
                            )}
                          </div>
                          <span className="text-sm text-gray-500">
                            {new Date(sop.uploaded_at).toLocaleDateString('zh-CN')}
                          </span>
                        </div>
                        <div className="text-xs text-gray-400 mt-1">
                          文件: {sop.filename} | 最后核验: {sop.last_verified || '未核验'}
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* AI比对风险Modal */}
      {showStalenessModal && selectedSop && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] overflow-hidden">
            <div className="p-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold">
                AI风险比对 - {selectedSop.process_name}
              </h3>
              <button
                onClick={() => setShowStalenessModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>
            <div className="p-4">
              {!stalenessResult ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-600"></div>
                  <span className="ml-3 text-gray-600">AI正在分析知识库...</span>
                </div>
              ) : stalenessResult.error ? (
                <div className="text-center py-8">
                  <p className="text-red-500">分析失败: {stalenessResult.error}</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* 风险等级 */}
                  <div className={`p-4 rounded-lg ${
                    stalenessResult.risk === 'high' ? 'bg-red-50 border border-red-200' :
                    stalenessResult.risk === 'medium' ? 'bg-yellow-50 border border-yellow-200' :
                    'bg-green-50 border border-green-200'
                  }`}>
                    <div className="flex items-center gap-2 mb-2">
                      {stalenessResult.risk === 'high' ? <XCircle className="text-red-500" size={20} /> :
                       stalenessResult.risk === 'medium' ? <AlertTriangle className="text-yellow-500" size={20} /> :
                       <CheckCircle className="text-green-500" size={20} />}
                      <span className={`font-semibold ${
                        stalenessResult.risk === 'high' ? 'text-red-700' :
                        stalenessResult.risk === 'medium' ? 'text-yellow-700' :
                        'text-green-700'
                      }`}>
                        风险等级: {stalenessResult.risk === 'high' ? '高' : stalenessResult.risk === 'medium' ? '中' : '低'}
                      </span>
                    </div>
                    <p className="text-gray-700">{stalenessResult.reason}</p>
                  </div>

                  {/* 建议 */}
                  {stalenessResult.suggestion && (
                    <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                      <h4 className="font-semibold text-blue-700 mb-2">AI建议</h4>
                      <p className="text-gray-700">{stalenessResult.suggestion}</p>
                    </div>
                  )}

                  {/* 相关文件 */}
                  {stalenessResult.related_files && stalenessResult.related_files.length > 0 && (
                    <div className="border border-gray-200 rounded-lg p-4">
                      <h4 className="font-semibold text-gray-700 mb-2">相关文档</h4>
                      <ul className="space-y-1">
                        {stalenessResult.related_files.map((file, idx) => (
                          <li key={idx} className="text-sm text-gray-600 flex items-center gap-2">
                            <span className="w-1.5 h-1.5 bg-gray-400 rounded-full"></span>
                            {file}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}