import { useState, useEffect, useRef } from 'react'
import { Disclosure } from '@headlessui/react'
import { ChevronDown, FileText, CheckCircle, AlertCircle, AlertTriangle, Eye } from 'lucide-react'
import { useToast } from '../hooks/useToast'

interface HealthStats {
  totalDocs: number
  totalQuestions: number
  hitRate: number
  topDocs: { filename: string; hits: number }[]
  zombieDocs: { filename: string; uploadedAt: Date }[]
  sopStats: {
    normal: number
    pending: number
    expired: number
    list: { filename: string; status: 'normal' | 'pending' | 'expired' }[]
  }
}

interface HealthPanelProps {
  refreshKey?: number
}

export default function HealthPanel({ refreshKey = 0 }: HealthPanelProps) {
  const [stats, setStats] = useState<HealthStats>({
    totalDocs: 12,
    totalQuestions: 3847,
    hitRate: 84,
    topDocs: [
      { filename: '员工手册.pdf', hits: 1234 },
      { filename: '贷款审批流程.pdf', hits: 856 },
      { filename: '客户服务规范.docx', hits: 623 },
    ],
    zombieDocs: [
      { filename: '2022年旧制度.pdf', uploadedAt: new Date(Date.now() - 30 * 86400000) },
      { filename: '历史培训材料.docx', uploadedAt: new Date(Date.now() - 45 * 86400000) },
    ],
    sopStats: {
      normal: 8,
      pending: 2,
      expired: 1,
      list: [
        { filename: '开户流程SOP.pdf', status: 'normal' },
        { filename: '转账操作规范.pdf', status: 'normal' },
        { filename: '挂失处理流程.pdf', status: 'pending' },
        { filename: '旧版审批流程.pdf', status: 'expired' },
      ],
    },
  })
  const [lastRefreshKey, setLastRefreshKey] = useState(refreshKey)
  const isFetching = useRef(false)
  const { showToast } = useToast()

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch('/api/feedback/health_stats')
        if (response.ok) {
          const data = await response.json()
          setStats(prev => ({
            ...prev,
            ...data,
            topDocs: data.topDocs || prev.topDocs,
            zombieDocs: data.zombieDocs || prev.zombieDocs,
            sopStats: data.sopStats ? { ...prev.sopStats, ...data.sopStats } : prev.sopStats,
          }))
        } else {
          throw new Error(`请求失败: ${response.status}`)
        }
      } catch (error) {
        console.error('Fetch health stats error:', error)
        showToast(error instanceof Error ? error.message : '获取健康度数据失败', 'error')
      }
    }
    
    if (lastRefreshKey !== refreshKey) {
      if (isFetching.current) return
      isFetching.current = true
      
      fetchData().finally(() => {
        isFetching.current = false
      })
      setLastRefreshKey(refreshKey)
    } else if (lastRefreshKey === 0 && !isFetching.current) {
      isFetching.current = true
      fetchData().finally(() => {
        isFetching.current = false
      })
    }
  }, [refreshKey, lastRefreshKey, showToast])

  const getHitRateColor = (rate: number) => {
    if (rate > 80) return 'text-green-600'
    if (rate >= 60) return 'text-yellow-600'
    return 'text-red-600'
  }

  const getHitRateBg = (rate: number) => {
    if (rate > 80) return 'bg-green-50'
    if (rate >= 60) return 'bg-yellow-50'
    return 'bg-red-50'
  }

  const maxHits = Math.max(...(stats.topDocs || []).map(d => d.hits), 1)

  const getDaysAgo = (date: Date) => {
    return Math.floor((Date.now() - date.getTime()) / 86400000)
  }

  const getSopIcon = (status: string) => {
    switch (status) {
      case 'normal': return <CheckCircle size={16} className="text-green-500" />
      case 'pending': return <AlertCircle size={16} className="text-yellow-500" />
      case 'expired': return <AlertTriangle size={16} className="text-red-500" />
      default: return null
    }
  }

  const getSopStatusText = (status: string) => {
    switch (status) {
      case 'normal': return '正常'
      case 'pending': return '待核验'
      case 'expired': return '严重过期'
      default: return status
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-gray-200 bg-white">
        <h2 className="text-lg font-semibold text-gray-800">知识库健康度</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        <div className="grid grid-cols-3 gap-3">
          <div className="bg-white rounded-xl p-4 text-center border border-gray-200 shadow-sm">
            <p className="text-2xl font-bold text-gray-800">{stats.totalDocs}</p>
            <p className="text-sm text-gray-500 mt-1">已入库文档</p>
            <p className="text-xs text-gray-400">篇</p>
          </div>
          <div className="bg-white rounded-xl p-4 text-center border border-gray-200 shadow-sm">
            <p className="text-2xl font-bold text-gray-800">{stats.totalQuestions.toLocaleString()}</p>
            <p className="text-sm text-gray-500 mt-1">问题索引</p>
            <p className="text-xs text-gray-400">条</p>
          </div>
          <div className={`rounded-xl p-4 text-center border border-gray-200 shadow-sm ${getHitRateBg(stats.hitRate)}`}>
            <p className={`text-2xl font-bold ${getHitRateColor(stats.hitRate)}`}>{stats.hitRate}%</p>
            <p className="text-sm text-gray-500 mt-1">7日命中率</p>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
          <h3 className="font-semibold text-gray-800 mb-3">文档贡献榜</h3>
          <div className="space-y-3">
            {(stats.topDocs || []).map((doc, idx) => (
              <div key={idx}>
                <div className="flex items-center justify-between text-sm mb-1">
                  <span className="text-gray-700 truncate flex-1">{doc.filename}</span>
                  <span className="text-gray-500 ml-2 flex-shrink-0">命中 {doc.hits} 次</span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full transition-all duration-500"
                    style={{ width: `${(doc.hits / maxHits) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
          <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <AlertTriangle size={16} className="text-yellow-500" />
            僵尸知识提醒
          </h3>
          <div className="space-y-2">
            {(stats.zombieDocs || []).map((doc, idx) => (
              <div key={idx} className="flex items-center justify-between p-3 bg-yellow-50 rounded-lg">
                <div className="flex items-center gap-2">
                  <FileText size={16} className="text-yellow-600" />
                  <span className="text-sm text-gray-700 truncate">{doc.filename}</span>
                  <span className="text-xs text-gray-400 flex-shrink-0">· 上传于{getDaysAgo(doc.uploadedAt)}天前</span>
                </div>
                <button className="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1">
                  <Eye size={12} />
                  查看
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
          <h3 className="font-semibold text-gray-800 mb-3">SOP核验状态</h3>
          <div className="flex items-center gap-4 mb-3">
            <div className="flex items-center gap-1 text-sm">
              <CheckCircle size={16} className="text-green-500" />
              <span className="text-gray-600">正常</span>
              <span className="font-semibold text-gray-800 ml-1">{stats.sopStats.normal}个</span>
            </div>
            <div className="flex items-center gap-1 text-sm">
              <AlertCircle size={16} className="text-yellow-500" />
              <span className="text-gray-600">待核验</span>
              <span className="font-semibold text-gray-800 ml-1">{stats.sopStats.pending}个</span>
            </div>
            <div className="flex items-center gap-1 text-sm">
              <AlertTriangle size={16} className="text-red-500" />
              <span className="text-gray-600">严重过期</span>
              <span className="font-semibold text-gray-800 ml-1">{stats.sopStats.expired}个</span>
            </div>
          </div>

          <Disclosure>
            {({ open }) => (
              <>
                <Disclosure.Button className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1">
                  查看详情
                  <ChevronDown
                    className={`w-4 h-4 transition-transform ${open ? 'rotate-180' : ''}`}
                  />
                </Disclosure.Button>
                <Disclosure.Panel className="mt-3 space-y-2">
                  {(stats.sopStats?.list || []).map((sop, idx) => (
                    <div key={idx} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div className="flex items-center gap-2">
                        {getSopIcon(sop.status)}
                        <span className="text-sm text-gray-700">{sop.filename}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          sop.status === 'normal' ? 'bg-green-100 text-green-600' :
                          sop.status === 'pending' ? 'bg-yellow-100 text-yellow-600' :
                          'bg-red-100 text-red-600'
                        }`}>
                          {getSopStatusText(sop.status)}
                        </span>
                      </div>
                      {sop.status !== 'normal' && (
                        <button className="text-xs text-blue-600 hover:text-blue-700 px-3 py-1 border border-blue-200 rounded hover:bg-blue-50">
                          核验
                        </button>
                      )}
                    </div>
                  ))}
                </Disclosure.Panel>
              </>
            )}
          </Disclosure>
        </div>
      </div>
    </div>
  )
}