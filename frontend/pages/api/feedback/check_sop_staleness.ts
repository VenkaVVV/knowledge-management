import type { NextApiRequest, NextApiResponse } from 'next'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { sop_id } = req.body

    if (!sop_id) {
      return res.status(400).json({ error: 'Missing sop_id' })
    }

    // 转发到后端
    const response = await fetch(`${BACKEND_URL}/feedback/check_sop_staleness`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ sop_id }),
    })

    if (!response.ok) {
      throw new Error(`Backend error: ${response.status}`)
    }

    const data = await response.json()
    res.status(200).json(data)
  } catch (error) {
    console.error('Check sop staleness proxy error:', error)
    res.status(500).json({ error: 'Internal server error' })
  }
}