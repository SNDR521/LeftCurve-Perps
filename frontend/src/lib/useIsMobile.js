import { useEffect, useState } from 'react'

// True when the viewport is phone-sized (< md). Drives the few places that
// need the breakpoint in JS (single AlertBell instance; disabling grid drag).
export default function useIsMobile(query = '(max-width: 767px)') {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches
  )
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = (e) => setMatches(e.matches)
    mq.addEventListener('change', onChange)
    setMatches(mq.matches)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return matches
}
