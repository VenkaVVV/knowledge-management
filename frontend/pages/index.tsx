import { useState, useRef, useEffect } from 'react'
import { v4 as uuidv4 } from 'uuid'
import { Menu } from '@headlessui/react'
import { ChevronDown, User } from 'lucide-react'
import ChatPanel from '../components/ChatPanel'
import UploadPanel from '../components/UploadPanel'
import MemoryPanel from '../components/MemoryPanel'
import HealthPanel from '../components/HealthPanel'
import BlindSpotPanel from '../components/BlindSpotPanel'
import SOPPanel from '../components/SOPPanel'

const users = [
  { id: 'user_001', name: '柜员-张三', role: '柜员' },
  { id: 'user_002', name: '客服-李四', role: '客服' },
  { id: 'user_003', name: '审批岗-王五', role: '审批岗' },
]

export default function Home() {
  const [currentUser, setCurrentUser] = useState(users[0])
  const [sessionId, setSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('chat_session_id')
      if (saved) return saved
    }
    return uuidv4()
  })
  const [memoryRefreshKey, setMemoryRefreshKey] = useState(0)
  const [healthRefreshKey, setHealthRefreshKey] = useState(0)
  const [activeTab, setActiveTab] = useState<'health' | 'sop' | 'blindspot'>('health')
  const [blindSpotCache, setBlindSpotCache] = useState<any>(null)
  const [blindSpotAnalyzedAt, setBlindSpotAnalyzedAt] = useState<string | null>(null)
  const [blindSpotBadge, setBlindSpotBadge] = useState(false)
  const [sopBadge, setSopBadge] = useState(false)
  const uploadPanelRef = useRef<HTMLDivElement>(null)
  
  // 保存到 localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('chat_session_id', sessionId)
    }
  }, [sessionId])

  const handleUserChange = (user: typeof users[0]) => {
    setCurrentUser(user)
    const newSessionId = uuidv4()
    setSessionId(newSessionId)
    localStorage.setItem('chat_session_id', newSessionId)
    setMemoryRefreshKey(prev => prev + 1)
  }

  const handleChatComplete = () => {
    // 延迟刷新，等待后台任务完成（write_memory 是后台异步任务）
    setTimeout(() => {
      setMemoryRefreshKey(prev => prev + 1)
    }, 3000) // 3秒后刷新，给后台任务足够时间
  }

  const handleUploadComplete = () => {
    setHealthRefreshKey(prev => prev + 1)
  }

  const handleUploadSop = () => {
    setActiveTab('health')
    uploadPanelRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const handleFeedbackResult = (data: any) => {
    if (data.trigger_blind_spot) {
      setBlindSpotBadge(true)
    }
    if (data.sop_affected) {
      setSopBadge(true)
    }
  }

  return (
    <div className="h-screen flex flex-col bg-gray-100 overflow-hidden">
      <nav className="bg-gray-800 px-6 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-500 rounded-lg flex items-center justify-center">
            <span className="text-white font-bold">AI</span>
          </div>
          <h1 className="text-white text-xl font-semibold">企业知识助手</h1>
        </div>

        <Menu as="div" className="relative">
          <Menu.Button className="flex items-center gap-2 px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors">
            <User size={18} />
            <span>{currentUser.name}</span>
            <ChevronDown size={16} />
          </Menu.Button>
          <Menu.Items className="absolute right-0 mt-2 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50">
            {users.map((user) => (
              <Menu.Item key={user.id}>
                {({ active }) => (
                  <button
                    onClick={() => handleUserChange(user)}
                    className={`
                      w-full text-left px-4 py-2 text-sm
                      ${active ? 'bg-gray-100' : ''}
                      ${currentUser.id === user.id ? 'text-blue-600 font-medium' : 'text-gray-700'}
                    `}
                  >
                    <div>{user.name}</div>
                    <div className="text-xs text-gray-400">{user.role}</div>
                  </button>
                )}
              </Menu.Item>
            ))}
          </Menu.Items>
        </Menu>
      </nav>

      <div className="flex-1 flex overflow-hidden min-h-0">
        <div className="w-1/4 flex flex-col bg-white border-r border-gray-200 overflow-hidden">
          <div ref={uploadPanelRef} className="flex-1 overflow-y-auto min-h-0">
            <UploadPanel onUploadComplete={handleUploadComplete} />
          </div>
          <div className="flex-1 border-t border-gray-200 overflow-hidden min-h-0">
            <MemoryPanel refreshKey={memoryRefreshKey} userId={currentUser.id} sessionId={sessionId} />
          </div>
        </div>

        <div className="w-2/4 overflow-hidden">
          <ChatPanel
            userId={currentUser.id}
            sessionId={sessionId || ''}
            onChatComplete={handleChatComplete}
            onFeedbackResult={handleFeedbackResult}
          />
        </div>

        <div className="w-1/4 flex flex-col bg-white border-l border-gray-200 overflow-hidden">
          <div className="flex border-b border-gray-200">
            <button
              onClick={() => setActiveTab('health')}
              className={`
                flex-1 px-4 py-3 text-sm font-medium transition-colors
                ${activeTab === 'health'
                  ? 'text-blue-600 border-b-2 border-blue-500 bg-blue-50'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'}
              `}
            >
              知识健康度
            </button>
            <button
              onClick={() => {
                setActiveTab('sop')
                setSopBadge(false)
              }}
              className={`
                flex-1 px-4 py-3 text-sm font-medium transition-colors relative
                ${activeTab === 'sop'
                  ? 'text-blue-600 border-b-2 border-blue-500 bg-blue-50'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'}
              `}
            >
              SOP管理
              {sopBadge && (
                <span 
                  className="absolute top-2 right-2 w-2 h-2 bg-red-500 rounded-full"
                />
              )}
            </button>
            <button
              onClick={() => {
                setActiveTab('blindspot')
                setBlindSpotBadge(false)
              }}
              className={`
                flex-1 px-4 py-3 text-sm font-medium transition-colors relative
                ${activeTab === 'blindspot'
                  ? 'text-blue-600 border-b-2 border-blue-500 bg-blue-50'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'}
              `}
            >
              盲区分析
              {blindSpotBadge && (
                <span 
                  className="absolute top-2 right-2 w-2 h-2 bg-red-500 rounded-full"
                />
              )}
            </button>
          </div>

          <div className="flex-1 overflow-y-auto min-h-0">
            {activeTab === 'health' ? (
              <HealthPanel refreshKey={healthRefreshKey} />
            ) : activeTab === 'sop' ? (
              <SOPPanel />
            ) : (
              <BlindSpotPanel 
                onUploadSop={handleUploadSop}
                cachedData={blindSpotCache}
                analyzedAt={blindSpotAnalyzedAt}
                onAnalyzeComplete={(data: any) => {
                  setBlindSpotCache(data)
                  // 使用后端返回的生成时间，如果没有则用当前时间
                  if (data.generatedAt) {
                    setBlindSpotAnalyzedAt(new Date(data.generatedAt).toLocaleString())
                  } else {
                    setBlindSpotAnalyzedAt(new Date().toLocaleString())
                  }
                }}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}