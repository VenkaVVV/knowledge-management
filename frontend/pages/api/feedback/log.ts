import type { NextApiRequest, NextApiResponse } from 'next'

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' })
  }

  try {
    const { user_id, query, session_id, feedback_type } = req.body

    if (!user_id || !query || !session_id || !feedback_type) {
      return res.status(400).json({ error: 'Missing required fields' })
    }

    // 转发到后端
    const response = await fetch(`${BACKEND_URL}/feedback/log`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id,
        query,
        session_id,
        feedback_type,
      }),
    })

    if (!response.ok) {
      throw new Error(`Backend error: ${response.status}`)
    }

    const data = await response.json()
    res.status(200).json(data)
  } catch (error) {
    console.error('Feedback log error:', error)
    res.status(500).json({ error: 'Internal server error' })
  }
}