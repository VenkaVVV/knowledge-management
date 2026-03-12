import type { NextApiRequest, NextApiResponse } from 'next'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const response = await fetch(`${BACKEND_URL}/documents`)
    const data = await response.json()
    res.status(response.status).json(data)
  } catch (error) {
    console.error('Documents proxy error:', error)
    res.status(500).json({ error: 'Internal server error' })
  }
}