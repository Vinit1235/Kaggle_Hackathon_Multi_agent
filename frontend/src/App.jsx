import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Domain definitions with icons
const DOMAIN_INFO = {
  youtube_creator: {
    icon: '🎬',
    title: 'YouTube Creator',
    description: 'Generate viral video ideas, scripts, thumbnails, and SEO — powered by a specialized creative team.',
  },
  legal_squad: {
    icon: '⚖️',
    title: 'Legal Squad',
    description: 'Draft contracts, verify compliance, and translate legal jargon into plain English.',
  },
}

function getAgentTagClass(agent) {
  const a = agent.toLowerCase()
  if (a === 'lead') return 'lead'
  if (a === 'critic') return 'critic'
  if (a === 'synthesizer') return 'synthesizer'
  if (a === 'system') return 'system'
  return 'worker'
}

function getStatusBadgeClass(status) {
  if (!status) return 'idle'
  const s = status.toLowerCase()
  if (s.includes('work') || s.includes('think') || s.includes('decompos') || s.includes('synthesi')) return 'working'
  if (s.includes('done') || s.includes('complete') || s.includes('approved')) return 'done'
  if (s.includes('fail') || s.includes('error')) return 'error'
  if (s.includes('review') || s.includes('revision')) return 'reviewing'
  return 'idle'
}

function formatTime(date) {
  return date.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function App() {
  // State
  const [domains, setDomains] = useState([])
  const [selectedDomain, setSelectedDomain] = useState(null)
  const [goal, setGoal] = useState('')
  const [sessionId, setSessionId] = useState(null)
  const [isRunning, setIsRunning] = useState(false)
  const [agentStates, setAgentStates] = useState({})
  const [feedItems, setFeedItems] = useState([])
  const [finalOutput, setFinalOutput] = useState(null)
  const [health, setHealth] = useState(null)

  const wsRef = useRef(null)
  const feedEndRef = useRef(null)

  // Fetch available domains on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/domains`)
      .then(r => r.json())
      .then(data => setDomains(data.domains || []))
      .catch(() => {
        // Use fallback domain data if backend isn't running
        setDomains([
          { id: 'youtube_creator', description: DOMAIN_INFO.youtube_creator.description, team_roles: ['Idea_Generator', 'Script_Writer', 'Visual_Director', 'SEO_Specialist', 'Critic'], workflow: [] },
          { id: 'legal_squad', description: DOMAIN_INFO.legal_squad.description, team_roles: ['Clause_Drafter', 'Compliance_Checker', 'Plain_Language_Translator', 'Critic'], workflow: [] },
        ])
      })

    fetch(`${API_BASE}/health`)
      .then(r => r.json())
      .then(setHealth)
      .catch(() => setHealth({ gemini_connected: false, redis_connected: false, db_initialized: false }))
  }, [])

  // Auto-scroll feed
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [feedItems])

  // Add feed item helper
  const addFeedItem = useCallback((agent, message, type = 'status') => {
    setFeedItems(prev => [...prev, { agent, message, type, time: new Date() }])
  }, [])

  // Connect WebSocket
  const connectWS = useCallback((sid) => {
    if (wsRef.current) wsRef.current.close()

    const wsProtocol = API_BASE.startsWith('https') ? 'wss' : 'ws'
    const wsHost = API_BASE.replace(/^https?:\/\//, '')
    const ws = new WebSocket(`${wsProtocol}://${wsHost}/ws/${sid}`)
    wsRef.current = ws

    ws.onopen = () => addFeedItem('System', 'Connected to live feed')

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)

        addFeedItem(msg.agent || 'System', msg.message || JSON.stringify(msg), msg.type)

        // Update agent states
        if (msg.agent && msg.agent !== 'System') {
          setAgentStates(prev => ({
            ...prev,
            [msg.agent]: {
              status: msg.type === 'task_complete' ? 'done' : msg.message,
              message: msg.message || '',
              preview: msg.preview || prev[msg.agent]?.preview || '',
            }
          }))
        }

        // Handle final output
        if (msg.type === 'final_output') {
          setFinalOutput(msg.content)
          setIsRunning(false)
        }

        // Handle workflow complete
        if (msg.type === 'workflow_complete') {
          setIsRunning(false)
        }

        // Handle errors
        if (msg.type === 'error') {
          setIsRunning(false)
        }
      } catch (e) {
        console.error('WS parse error:', e)
      }
    }

    ws.onclose = () => addFeedItem('System', 'Live feed disconnected')
    ws.onerror = () => addFeedItem('System', 'Connection error')
  }, [addFeedItem])

  // Run workflow
  const handleRun = async () => {
    if (!selectedDomain || !goal.trim()) return

    setIsRunning(true)
    setFeedItems([])
    setAgentStates({})
    setFinalOutput(null)

    addFeedItem('System', `Starting ${DOMAIN_INFO[selectedDomain]?.title || selectedDomain} workflow...`)

    try {
      const resp = await fetch(`${API_BASE}/api/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          domain: selectedDomain,
          user_goal: goal,
          user_preferences: {},
        }),
      })
      const data = await resp.json()
      setSessionId(data.session_id)
      addFeedItem('System', `Session created: ${data.session_id.slice(0, 8)}...`)
      connectWS(data.session_id)
    } catch (e) {
      addFeedItem('System', `Failed to start: ${e.message}`)
      setIsRunning(false)
    }
  }

  // Get agents for selected domain
  const currentAgents = domains.find(d => d.id === selectedDomain)?.team_roles || []

  return (
    <div className="app-container">
      {/* ── Header ─────────────────────────────────────── */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-icon">⚡</div>
          <div className="brand-text">
            <h1>AI Agency Platform</h1>
            <span>Gemma 4 Multi-Agent System</span>
          </div>
        </div>
        <div className="header-status">
          <div className="status-indicator">
            <div className={`status-dot ${health?.gemini_connected ? 'online' : 'offline'}`} />
            Gemini
          </div>
          <div className="status-indicator">
            <div className={`status-dot ${health?.redis_connected ? 'online' : 'warning'}`} />
            Redis
          </div>
          <div className="status-indicator">
            <div className={`status-dot ${health?.db_initialized ? 'online' : 'offline'}`} />
            TaskBox
          </div>
        </div>
      </header>

      {/* ── Domain Selector ────────────────────────────── */}
      <section className="domain-section">
        <div className="section-title">Select Domain</div>
        <div className="domain-grid">
          {domains.map(domain => {
            const info = DOMAIN_INFO[domain.id] || { icon: '🔧', title: domain.id }
            return (
              <div
                key={domain.id}
                id={`domain-${domain.id}`}
                className={`domain-card ${selectedDomain === domain.id ? 'selected' : ''}`}
                onClick={() => !isRunning && setSelectedDomain(domain.id)}
              >
                <div className="domain-card-content">
                  <div className="domain-icon">{info.icon}</div>
                  <h3>{info.title}</h3>
                  <p>{domain.description}</p>
                  <div className="domain-agents">
                    {domain.team_roles.map(role => (
                      <span key={role} className="agent-badge">{role}</span>
                    ))}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      {/* ── Goal Input ─────────────────────────────────── */}
      <section className="goal-section">
        <div className="section-title">Your Goal</div>
        <div className="goal-input-wrapper">
          <textarea
            id="goal-input"
            className="goal-input"
            placeholder={
              selectedDomain === 'youtube_creator'
                ? 'e.g., "Create a 10-minute tech review video about the latest AI tools for developers"'
                : selectedDomain === 'legal_squad'
                ? 'e.g., "Draft a freelance contractor agreement with IP ownership and NDA clauses"'
                : 'Select a domain above, then describe your goal...'
            }
            value={goal}
            onChange={e => setGoal(e.target.value)}
            disabled={isRunning}
            rows={2}
          />
          <button
            id="run-button"
            className={`run-button ${isRunning ? 'running' : ''}`}
            onClick={handleRun}
            disabled={!selectedDomain || !goal.trim() || isRunning}
          >
            {isRunning ? '⏳ Running...' : '▶ Launch Team'}
          </button>
        </div>
      </section>

      {/* ── Agent Status Cards ─────────────────────────── */}
      {currentAgents.length > 0 && (
        <section className="agents-section">
          <div className="section-title">Agent Team</div>
          <div className="agents-grid">
            {currentAgents.map(role => {
              const state = agentStates[role] || {}
              const statusClass = getStatusBadgeClass(state.status)
              return (
                <div
                  key={role}
                  id={`agent-card-${role}`}
                  className={`agent-card ${statusClass === 'working' ? 'active' : ''} ${statusClass === 'done' ? 'completed' : ''} ${statusClass === 'error' ? 'failed' : ''}`}
                >
                  <div className="agent-card-header">
                    <span className="agent-name">{role}</span>
                    <span className={`agent-status-badge ${statusClass}`}>
                      {statusClass === 'working' && <span className="agent-spinner" />}
                      {state.status ? statusClass.charAt(0).toUpperCase() + statusClass.slice(1) : 'Idle'}
                    </span>
                  </div>
                  <div className="agent-message">
                    {state.message || 'Waiting for assignment...'}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* ── Live Feed ──────────────────────────────────── */}
      {feedItems.length > 0 && (
        <section className="feed-section">
          <div className="feed-container">
            <div className="feed-header">
              <h3>📡 Live Agent Feed</h3>
              <span className="feed-count">{feedItems.length} events</span>
            </div>
            <div className="feed-list">
              {feedItems.map((item, i) => (
                <div key={i} className="feed-item">
                  <span className="feed-timestamp">{formatTime(item.time)}</span>
                  <span className={`feed-agent-tag ${getAgentTagClass(item.agent)}`}>
                    {item.agent}
                  </span>
                  <span className="feed-message">{item.message}</span>
                </div>
              ))}
              <div ref={feedEndRef} />
            </div>
          </div>
        </section>
      )}

      {/* ── Final Output ───────────────────────────────── */}
      {finalOutput && (
        <section className="output-section">
          <div className="output-container">
            <div className="output-header">
              <span>✅</span>
              <h3>Final Output</h3>
            </div>
            <div className="output-content">{finalOutput}</div>
          </div>
        </section>
      )}

      {/* ── Empty State ────────────────────────────────── */}
      {!isRunning && feedItems.length === 0 && (
        <div className="empty-state">
          <div className="empty-state-icon">🤖</div>
          <h3>Ready to Launch</h3>
          <p>Select a domain, describe your goal, and watch your AI team collaborate in real-time.</p>
        </div>
      )}
    </div>
  )
}

export default App
