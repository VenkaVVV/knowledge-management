import { useState, useRef, useEffect } from 'react'
import { Popover } from '@headlessui/react'
import { Send, ThumbsUp, ThumbsDown, Loader2 } from 'lucide-react'
import { useToast } from '../hooks/useToast'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
}

interface Source {
  type: 'meta_rule' | 'insight' | 'fact' | 'sop' | 'knowledge'
  label: string
  content: string
}

interface ChatPanelProps {
  userId: string
  sessionId: string
  onChatComplete?: () => void
  onFeedbackResult?: (data: any) => void
}

export default function ChatPanel({ userId, sessionId, onChatComplete, onFeedbackResult }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputText, setInputText] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [lastSources, setLastSources] = useState<Source[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [feedbackGiven, setFeedbackGiven] = useState<Record<string, { given: boolean, type?: string }>>({})
  const [feedbackError, setFeedbackError] = useState<Record<string, boolean>>({})
  const [feedbackResult, setFeedbackResult] = useState<{ messageId: string; message: string; color: 'blue' | 'yellow' | 'orange' } | null>(null)
  const [streamInterrupted, setStreamInterrupted] = useState<string | null>(null)
  const { showToast } = useToast()

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // 加载历史记录 - 按用户加载，不按会话
  useEffect(() => {
    const loadHistory = async () => {
      try {
        console.log(`[ChatPanel] 加载历史记录，user_id=${userId}`)
        const response = await fetch(`/api/chat/history?user_id=${userId}`)
        if (response.ok) {
          const result = await response.json()
          console.log(`[ChatPanel] 历史记录响应:`, result)
          const messages = result.data?.messages || result.messages || []
          // 转换消息格式以匹配前端期望的格式
          const formattedMessages: Message[] = messages.map((msg: any, index: number) => ({
            id: `history-${index}`,
            role: msg.role,
            content: msg.content,
          }))
          console.log(`[ChatPanel] 格式化后的消息:`, formattedMessages)
          setMessages(formattedMessages)
        }
      } catch (error) {
        console.error('加载历史记录失败:', error)
      }
    }
    
    if (userId) {
      loadHistory()
    }
  }, [userId])

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSend = async () => {
    if (!inputText.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: inputText.trim(),
    }

    const aiMessageId = (Date.now() + 1).toString()
    const aiMessage: Message = {
      id: aiMessageId,
      role: 'assistant',
      content: '',
    }

    setMessages(prev => [...prev, userMessage, aiMessage])
    setInputText('')
    setIsLoading(true)
    setLastSources([])
    setStreamInterrupted(null)

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          session_id: sessionId,
          query: userMessage.content,
        }),
      })

      if (!response.ok) {
        throw new Error(`请求失败: ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('响应为空')
      }

      let streamDone = false

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            streamDone = true
            break
          }

          const lines = decoder.decode(value).split('\n')
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6)
              if (dataStr === '[DONE]') {
                streamDone = true
                continue
              }

              try {
                const data = JSON.parse(dataStr)
                if (data.type === 'text') {
                  setMessages(prev => prev.map(msg =>
                    msg.id === aiMessageId
                      ? { ...msg, content: msg.content + data.content }
                      : msg
                  ))
                }
                if (data.type === 'sources') {
                  setLastSources(data.content)
                  setMessages(prev => prev.map(msg =>
                    msg.id === aiMessageId
                      ? { ...msg, sources: data.content }
                      : msg
                  ))
                }
              } catch {
                // Ignore parse errors
              }
            }
          }
        }
      } catch (streamError) {
        console.error('Stream error:', streamError)
        if (!streamDone) {
          setStreamInterrupted(aiMessageId)
        }
      }

      setIsLoading(false)
      if (streamDone) {
        onChatComplete?.()
      }
    } catch (error) {
      console.error('Chat error:', error)
      showToast(error instanceof Error ? error.message : '发送消息失败，请重试', 'error')
      setIsLoading(false)
      setMessages(prev => prev.filter(msg => msg.id !== aiMessageId))
    }
  }

  const handleFeedback = async (messageId: string, helpful: boolean, reason?: string) => {
    if (feedbackGiven[messageId]?.given) return

    const reasonToTypeMap: Record<string, string> = {
      '答案不准确': 'not_accurate',
      '信息已过时': 'outdated',
      '没有回答我的问题': 'not_answered',
    }

    const feedbackType = helpful ? 'helpful' : reasonToTypeMap[reason!]

    const userQuery = messages.find((msg, idx) => {
      const nextMsg = messages[idx + 1]
      return nextMsg?.id === messageId && msg.role === 'user'
    })?.content || ''

    try {
      const response = await fetch('/api/feedback/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          query: userQuery,
          session_id: sessionId,
          feedback_type: feedbackType,
        }),
      })

      if (!response.ok) {
        throw new Error('反馈提交失败')
      }

      const result = await response.json()
      const data = result.data

      setFeedbackGiven(prev => ({ ...prev, [messageId]: { given: true, type: feedbackType } }))
      setFeedbackError(prev => ({ ...prev, [messageId]: false }))

      // 显示提示条
      setFeedbackResult({
        messageId,
        message: data.message,
        color: data.color,
      })

      // 通知父组件更新 Tab 红点
      onFeedbackResult?.(data)

      // 3秒后自动隐藏提示条
      setTimeout(() => {
        setFeedbackResult(null)
      }, 3000)
    } catch (error) {
      console.error('Feedback error:', error)
      setFeedbackError(prev => ({ ...prev, [messageId]: true }))
      showToast(error instanceof Error ? error.message : '记录失败，请重试', 'error')
    }
  }

  const getSourceBadgeColor = (type: string) => {
    switch (type) {
      case 'meta_rule': return 'bg-gray-100 text-gray-600'
      case 'insight': return 'bg-blue-100 text-blue-600'
      case 'fact': return 'bg-green-100 text-green-600'
      case 'sop': return 'bg-orange-100 text-orange-600'
      case 'knowledge': return 'bg-yellow-100 text-yellow-600'
      default: return 'bg-gray-100 text-gray-600'
    }
  }

  return (
    <div className="flex flex-col h-full bg-white border-r border-gray-200">
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <div className="text-6xl mb-4">🤖</div>
            <p className="text-lg font-medium">企业知识助手</p>
            <p className="text-sm">请输入您的问题开始对话</p>
          </div>
        )}
        
        {messages.map((message) => (
          <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] ${message.role === 'user' ? 'order-2' : 'order-1'}`}>
              <div className={`
                p-4 rounded-2xl
                ${message.role === 'user' 
                  ? 'bg-blue-500 text-white rounded-tr-sm' 
                  : 'bg-white border border-gray-200 text-gray-800 rounded-tl-sm shadow-sm'}
              `}>
                  <p className="whitespace-pre-wrap">{message.content}</p>
                  {streamInterrupted === message.id && (
                    <p className="mt-2 text-sm text-red-600 flex items-center gap-1">
                      ⚠️ 回答已中断
                    </p>
                  )}
                </div>
              
              {message.role === 'assistant' && message.sources && message.sources.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-2">
                  {message.sources.map((source, idx) => (
                    <Popover key={idx} className="relative">
                      <Popover.Button className={`
                        px-2 py-1 text-xs font-medium rounded-full
                        ${getSourceBadgeColor(source.type)}
                        hover:opacity-80 transition-opacity
                      `}>
                        {source.label}
                      </Popover.Button>
                      <Popover.Panel className="absolute z-50 w-80 p-3 mt-2 bg-white border border-gray-200 rounded-lg shadow-lg">
                        <p className="text-sm text-gray-700">{source.content}</p>
                      </Popover.Panel>
                    </Popover>
                  ))}
                </div>
              )}
              
                {message.role === 'assistant' && message.content && (
                 <div className="space-y-2 mt-2">
                   {/* 提示条 - 显示在反馈区域 */}
                   {feedbackResult?.messageId === message.id && (
                     <div className={`p-3 rounded-lg border-l-4 ${
                       feedbackResult.color === 'blue' ? 'bg-blue-50 border-blue-500' :
                       feedbackResult.color === 'yellow' ? 'bg-yellow-50 border-yellow-500' :
                       'bg-orange-50 border-orange-500'
                     }`}>
                       <p className={`text-sm ${
                         feedbackResult.color === 'blue' ? 'text-blue-700' :
                         feedbackResult.color === 'yellow' ? 'text-yellow-800' :
                         'text-orange-700'
                       }`}>
                         {feedbackResult.message}
                       </p>
                     </div>
                   )}
                   
                   {!feedbackGiven[message.id]?.given ? (
                     <div className="flex gap-2">
                       <button
                         onClick={() => handleFeedback(message.id, true)}
                         className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-green-600 hover:bg-green-50 rounded transition-colors"
                       >
                         <ThumbsUp size={14} />
                         有帮助
                       </button>
                       <Popover className="relative">
                         <Popover.Button className="flex items-center gap-1 px-2 py-1 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors">
                           <ThumbsDown size={14} />
                           没找到想要的
                         </Popover.Button>
                         <Popover.Panel className="absolute right-0 z-50 w-48 p-3 mt-2 bg-white border border-gray-200 rounded-lg shadow-lg">
                           <p className="text-sm font-medium text-gray-700 mb-2">请选择原因：</p>
                           <div className="space-y-2">
                             {['答案不准确', '信息已过时', '没有回答我的问题'].map((reason) => (
                               <button
                                 key={reason}
                                 onClick={() => handleFeedback(message.id, false, reason)}
                                 className="block w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded"
                               >
                                 ○ {reason}
                               </button>
                             ))}
                           </div>
                         </Popover.Panel>
                       </Popover>
                     </div>
                   ) : (
                     <div className="space-y-2">
                       <span className="text-xs text-gray-400 px-2 py-1">感谢您的反馈</span>
                       {feedbackError[message.id] ? (
                         <div className="text-xs text-red-600 px-3 py-1 bg-red-50 rounded">
                           记录失败，请重试
                         </div>
                       ) : feedbackGiven[message.id]?.type && feedbackGiven[message.id].type !== 'helpful' && (
                         <div className={`text-xs px-3 py-1 rounded ${
                           feedbackGiven[message.id].type === 'not_accurate' 
                             ? 'bg-blue-50 text-blue-600' 
                             : feedbackGiven[message.id].type === 'outdated' 
                             ? 'bg-yellow-50 text-yellow-700' 
                             : 'bg-orange-50 text-orange-600'
                         }`}>
                           {feedbackGiven[message.id].type === 'not_accurate' 
                             ? '📝 已记录，知识管理员将收到更新提醒' 
                             : feedbackGiven[message.id].type === 'outdated' 
                             ? '⚠️ 已标记，对应SOP将进入核验队列' 
                             : '🔍 已记录，该问题将进入盲区分析'}
                         </div>
                       )}
                     </div>
                   )}
                 </div>
               )}
            </div>
          </div>
        ))}
        
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 p-4 rounded-2xl rounded-tl-sm shadow-sm">
              <Loader2 className="w-5 h-5 animate-spin text-blue-500" />
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>
      
      <div className="p-4 border-t border-gray-200">
        <div className="flex gap-2">
          <input
            type="text"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSend()}
            placeholder="输入您的问题..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-full focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            disabled={isLoading || !inputText.trim()}
            className="px-4 py-2 bg-blue-500 text-white rounded-full hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={20} />
          </button>
        </div>
      </div>
    </div>
  )
}