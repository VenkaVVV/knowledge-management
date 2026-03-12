import type { NextApiRequest, NextApiResponse } from 'next'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  const { proxy, ...queryParams } = req.query
  const path = Array.isArray(proxy) ? proxy.join('/') : proxy

  // 构建查询字符串
  const searchParams = new URLSearchParams()
  Object.entries(queryParams).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach(v => searchParams.append(key, v))
    } else if (value !== undefined) {
      searchParams.append(key, value)
    }
  })
  const queryString = searchParams.toString()
  const url = `${BACKEND_URL}/${path}${queryString ? '?' + queryString : ''}`

  try {
    const { method, headers, body } = req
    const response = await fetch(url, {
      method,
      headers: {
        'content-type': headers['content-type'] || 'application/json',
      },
      body: method !== 'GET' && method !== 'HEAD' ? body : undefined,
    })

    const contentType = response.headers.get('content-type')
    if (contentType?.includes('application/json')) {
      const data = await response.json()
      res.status(response.status).json(data)
    } else {
      const data = await response.text()
      res.status(response.status).send(data)
    }
  } catch (error) {
    console.error('Proxy error:', error)
    res.status(500).json({ error: 'Internal server error' })
  }
}