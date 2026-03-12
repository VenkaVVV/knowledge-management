import type { NextApiRequest, NextApiResponse } from 'next'
import { Readable } from 'stream'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// 禁用默认的 bodyParser，允许原始请求体通过
export const config = {
  api: {
    bodyParser: false,
  },
}

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    // 将 Next.js 请求转换为 Node.js 可读流
    const chunks: Buffer[] = []
    for await (const chunk of req) {
      chunks.push(chunk)
    }
    const bodyBuffer = Buffer.concat(chunks)

    // 直接透传到后端，保持原始 multipart/form-data 格式
    const response = await fetch(`${BACKEND_URL}/upload`, {
      method: 'POST',
      headers: {
        'content-type': req.headers['content-type'] || 'multipart/form-data',
        'content-length': bodyBuffer.length.toString(),
      },
      body: bodyBuffer,
    })

    const data = await response.json()
    res.status(response.status).json(data)
  } catch (error) {
    console.error('Upload proxy error:', error)
    res.status(500).json({ error: 'Internal server error' })
  }
}