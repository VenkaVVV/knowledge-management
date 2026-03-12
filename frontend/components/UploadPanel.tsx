import { useState, useRef, useEffect } from 'react'
import { Upload, X, FileText, Trash2, Loader2, Eye } from 'lucide-react'
import { Dialog } from '@headlessui/react'
import { useToast } from '../hooks/useToast'

interface Document {
  id: string
  filename: string
  status: 'parsing' | 'vectorizing' | 'indexing' | 'completed' | 'failed'
  chunks: number
  questions: number
  hit_count: number
  uploadedAt: Date
}

interface PreviewData {
  filename: string
  file_type: string
  upload_time: string
  total_chunks: number
  total_questions: number
  hit_count: number
  chunks: Array<{
    chunk_id: string
    content: string
    source_type: string
    created_at: string
  }>
  questions: Array<{
    question: string
    chunk_id: string
    source_type: string
  }>
}

interface UploadPanelProps {
  onUploadComplete?: () => void
}

type DocType = 'knowledge' | 'sop'

export default function UploadPanel({ onUploadComplete }: UploadPanelProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [showTypeModal, setShowTypeModal] = useState(false)
  const [showPreviewModal, setShowPreviewModal] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [docType, setDocType] = useState<DocType>('knowledge')
  const [sopInfo, setSopInfo] = useState({
    processName: '',
    roles: [] as string[],
    effectiveDate: '',
  })
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(false)
  const [previewDoc, setPreviewDoc] = useState<Document | null>(null)
  const [previewData, setPreviewData] = useState<PreviewData | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { showToast } = useToast()

  // 加载文档列表
  const loadDocuments = async () => {
    try {
      setLoading(true)
      const response = await fetch('/api/documents')
      if (!response.ok) {
        throw new Error('获取文档列表失败')
      }
      const data = await response.json()
      if (data.status === 'success' && data.documents) {
        setDocuments(data.documents.map((doc: any) => ({
          id: doc.id.toString(),
          filename: doc.filename,
          status: doc.status || 'completed',
          chunks: doc.chunk_count || 0,
          questions: doc.question_count || 0,
          hit_count: doc.hit_count || 0,
          uploadedAt: new Date(doc.uploaded_at),
        })))
      }
    } catch (error) {
      console.error('加载文档列表失败:', error)
      showToast('加载文档列表失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDocuments()
  }, [])

  // 加载预览数据
  const loadPreview = async (filename: string) => {
    setPreviewLoading(true)
    try {
      const response = await fetch(`/api/documents/${encodeURIComponent(filename)}/preview`)
      if (!response.ok) {
        throw new Error('获取预览数据失败')
      }
      const data = await response.json()
      if (data.status === 'success') {
        setPreviewData(data)
      } else {
        throw new Error(data.message || '获取预览数据失败')
      }
    } catch (error) {
      console.error('加载预览失败:', error)
      showToast('加载预览失败', 'error')
    } finally {
      setPreviewLoading(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      handleFileSelect(files[0])
    }
  }

  const handleFileSelect = (file: File) => {
    const allowedTypes = ['.pdf', '.docx', '.txt']
    const fileExt = file.name.toLowerCase().substring(file.name.lastIndexOf('.'))
    if (!allowedTypes.includes(fileExt)) {
      alert('只支持PDF、DOCX和TXT文件')
      return
    }
    setSelectedFile(file)
    setShowTypeModal(true)
  }

  const handleUpload = async () => {
    if (!selectedFile) return

    setShowTypeModal(false)

    const newDoc: Document = {
      id: Date.now().toString(),
      filename: selectedFile.name,
      status: 'parsing',
      chunks: 0,
      questions: 0,
      hit_count: 0,
      uploadedAt: new Date(),
    }

    setDocuments(prev => [newDoc, ...prev])
    setSelectedFile(null)
    setDocType('knowledge')
    setSopInfo({ processName: '', roles: [], effectiveDate: '' })

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)
      formData.append('doc_type', docType)
      if (docType === 'sop') {
        formData.append('process_name', sopInfo.processName)
        formData.append('roles', JSON.stringify(sopInfo.roles))
        formData.append('effective_date', sopInfo.effectiveDate)
      }

      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ error: '上传失败' }))
        throw new Error(errorData.error || `上传失败: ${response.status}`)
      }

      const data = await response.json()

      setDocuments(prev => prev.map(d =>
        d.id === newDoc.id ? { ...d, status: 'vectorizing' } : d
      ))

      setTimeout(() => {
        setDocuments(prev => prev.map(d =>
          d.id === newDoc.id ? { ...d, status: 'indexing' } : d
        ))
      }, 2000)

      setTimeout(() => {
        setDocuments(prev => prev.map(d =>
          d.id === newDoc.id
            ? { ...d, status: 'completed', chunks: data.chunks_count || 0, hit_count: 0 }
            : d
        ))
        showToast('文档上传成功！问题索引正在后台生成中...', 'success')
        onUploadComplete?.()
        // 上传成功后刷新文档列表以获取完整数据（包含问题索引数）
        loadDocuments()
      }, 4000)

    } catch (error) {
      console.error('Upload error:', error)
      setDocuments(prev => prev.map(d =>
        d.id === newDoc.id ? { ...d, status: 'failed' } : d
      ))
      showToast(error instanceof Error ? error.message : '文档上传失败', 'error')
    }
  }

  const handleDelete = (docId: string) => {
    if (confirm('确定要删除这个文档吗？')) {
      setDocuments(prev => prev.filter(d => d.id !== docId))
    }
  }

  const handlePreviewClick = (doc: Document) => {
    setPreviewDoc(doc)
    setShowPreviewModal(true)
    loadPreview(doc.filename)
  }

  const getStatusBadge = (status: Document['status']) => {
    const badges = {
      parsing: { text: '解析中', icon: '🔄', color: 'bg-blue-100 text-blue-600' },
      vectorizing: { text: '向量化中', icon: '⚙️', color: 'bg-purple-100 text-purple-600' },
      indexing: { text: '生成索引中', icon: '🧠', color: 'bg-yellow-100 text-yellow-600' },
      completed: { text: '完成', icon: '✅', color: 'bg-green-100 text-green-600' },
      failed: { text: '失败', icon: '❌', color: 'bg-red-100 text-red-600' },
    }
    return badges[status]
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">文档上传</h2>
        
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`
            border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-all
            ${isDragging 
              ? 'border-blue-500 bg-blue-50' 
              : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'}
          `}
        >
          <Upload className="mx-auto h-10 w-10 text-gray-400 mb-3" />
          <p className="text-sm font-medium text-gray-600">拖拽文件到此处或点击上传</p>
          <p className="text-xs text-gray-400 mt-1">支持 PDF、DOCX、TXT 格式</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
            className="hidden"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 scrollbar-thin">
        <h3 className="text-sm font-medium text-gray-500 mb-3">已上传文件</h3>
        <div className="space-y-3">
          {documents.map((doc) => {
            const badge = getStatusBadge(doc.status)
            return (
              <div key={doc.id} className="bg-white border border-gray-200 rounded-lg p-3">
                <div className="flex items-start gap-3">
                  <FileText className="w-8 h-8 text-gray-400 flex-shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">
                      {doc.filename}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full ${badge.color}`}>
                        {badge.icon} {badge.text}
                      </span>
{doc.status === 'completed' && (
  <span className="text-xs text-gray-400">
    {doc.chunks}个chunk · {doc.questions}条问题索引 · {doc.hit_count}次命中
  </span>
)}
                    </div>
                  </div>
                </div>
                {doc.status === 'completed' && (
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={() => handlePreviewClick(doc)}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 rounded transition-colors"
                    >
                      <Eye size={14} />
                      预览
                    </button>
                    <button
                      onClick={() => handleDelete(doc.id)}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded transition-colors"
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* 上传类型选择弹窗 */}
      <Dialog open={showTypeModal} onClose={() => setShowTypeModal(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-md w-full bg-white rounded-xl shadow-lg">
            <div className="p-6">
              <Dialog.Title className="text-lg font-semibold text-gray-800 mb-4">
                选择文档类型
              </Dialog.Title>
              
              <div className="space-y-4">
                <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
                  <input
                    type="radio"
                    name="docType"
                    value="knowledge"
                    checked={docType === 'knowledge'}
                    onChange={() => setDocType('knowledge')}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-gray-700">普通知识文档</span>
                </label>
                
                <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50">
                  <input
                    type="radio"
                    name="docType"
                    value="sop"
                    checked={docType === 'sop'}
                    onChange={() => setDocType('sop')}
                    className="w-4 h-4 text-blue-600"
                  />
                  <span className="text-gray-700">SOP操作手册</span>
                </label>

                {docType === 'sop' && (
                  <div className="border-t pt-4 space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        流程名称
                      </label>
                      <input
                        type="text"
                        value={sopInfo.processName}
                        onChange={(e) => setSopInfo(prev => ({ ...prev, processName: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="请输入流程名称"
                      />
                    </div>
                    
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        适用岗位
                      </label>
                      <div className="flex gap-2">
                        {['柜员', '客服', '审批'].map((role) => (
                          <label key={role} className="flex items-center gap-2 px-3 py-2 border rounded-lg cursor-pointer hover:bg-gray-50">
                            <input
                              type="checkbox"
                              checked={sopInfo.roles.includes(role)}
                              onChange={(e) => {
                                setSopInfo(prev => ({
                                  ...prev,
                                  roles: e.target.checked
                                    ? [...prev.roles, role]
                                    : prev.roles.filter(r => r !== role)
                                }))
                              }}
                              className="w-4 h-4 text-blue-600"
                            />
                            <span className="text-sm">{role}</span>
                          </label>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        生效日期
                      </label>
                      <input
                        type="date"
                        value={sopInfo.effectiveDate}
                        onChange={(e) => setSopInfo(prev => ({ ...prev, effectiveDate: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-3 mt-6">
                <button
                  onClick={() => setShowTypeModal(false)}
                  className="px-4 py-2 text-gray-600 hover:text-gray-800 transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleUpload}
                  className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
                >
                  确认上传
                </button>
              </div>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>

      {/* 文档预览弹窗 */}
      <Dialog open={showPreviewModal} onClose={() => setShowPreviewModal(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/50" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-4xl w-full bg-white rounded-xl shadow-2xl max-h-[90vh] flex flex-col">
            {/* 头部 */}
            <div className="p-6 border-b border-gray-200 bg-gray-50 rounded-t-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <FileText className="w-8 h-8 text-blue-600" />
                  <div>
                    <Dialog.Title className="text-xl font-bold text-gray-900">
                      {previewDoc?.filename}
                    </Dialog.Title>
                    <p className="text-sm text-gray-500 mt-1">
                      {previewLoading ? '加载中...' : 
                        previewData ? `${previewData.file_type === 'sop' ? 'SOP操作手册' : '普通知识文档'} · ${new Date(previewData.upload_time).toLocaleString()}` : ''}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setShowPreviewModal(false)}
                  className="p-2 hover:bg-gray-200 rounded-full transition-colors"
                >
                  <X size={24} className="text-gray-500" />
                </button>
              </div>
              
              {/* 统计信息 */}
              {!previewLoading && previewData && (
                <div className="flex gap-6 mt-4 pt-4 border-t border-gray-200">
                  <div className="flex items-center gap-2">
                    <span className="text-2xl font-bold text-blue-600">{previewData.total_chunks}</span>
                    <span className="text-sm text-gray-500">个分块</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-2xl font-bold text-green-600">{previewData.total_questions}</span>
                    <span className="text-sm text-gray-500">条问题索引</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-2xl font-bold text-purple-600">{previewData.hit_count}</span>
                    <span className="text-sm text-gray-500">次命中</span>
                  </div>
                </div>
              )}
            </div>

            {/* 内容区域 */}
            <div className="flex-1 overflow-y-auto p-6">
              {previewLoading ? (
                <div className="flex flex-col items-center justify-center h-64">
                  <Loader2 className="w-10 h-10 text-blue-500 animate-spin mb-4" />
                  <p className="text-gray-500">加载预览数据中...</p>
                </div>
              ) : previewData ? (
                <div className="space-y-8">
                  {/* 文档分块内容 */}
                  <section>
                    <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                      <span className="w-1 h-6 bg-blue-500 rounded-full"></span>
                      文档分块内容
                      <span className="text-sm font-normal text-gray-500">（共 {previewData.total_chunks} 个）</span>
                    </h3>
                    <div className="space-y-3">
                      {previewData.chunks.map((chunk, index) => (
                        <div key={chunk.chunk_id} className="bg-gray-50 rounded-lg p-4 border border-gray-200">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-semibold text-blue-600 bg-blue-100 px-2 py-1 rounded">
                              Chunk {index + 1}/{previewData.total_chunks}
                            </span>
                            <span className="text-xs text-gray-400">ID: {chunk.chunk_id}</span>
                          </div>
                          <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                            {chunk.content}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>

                  {/* 索引问题清单 */}
                  <section>
                    <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2">
                      <span className="w-1 h-6 bg-green-500 rounded-full"></span>
                      本文件生成的索引问题清单
                      <span className="text-sm font-normal text-gray-500">（共 {previewData.total_questions} 条）</span>
                    </h3>
                    <div className="bg-green-50 rounded-lg p-4 border border-green-200">
                      <ol className="space-y-3">
                        {previewData.questions.map((q, index) => (
                          <li key={index} className="flex items-start gap-3 text-sm">
                            <span className="flex-shrink-0 w-6 h-6 bg-green-500 text-white rounded-full flex items-center justify-center text-xs font-bold">
                              {index + 1}
                            </span>
                            <div className="flex-1">
                              <p className="text-gray-800 font-medium">{q.question}</p>
                              <p className="text-xs text-gray-500 mt-1">关联 Chunk: {q.chunk_id}</p>
                            </div>
                          </li>
                        ))}
                      </ol>
                    </div>
                  </section>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-64">
                  <p className="text-gray-500">加载预览数据失败</p>
                </div>
              )}
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  )
}