import { useEffect, useState } from 'react'
import api from '../services/api'

/** Lädt ein geschütztes Bild per authentifiziertem Blob-Fetch (img kann
 *  keinen Bearer-Header senden) und rendert es. */
export default function AuthImage({ src, alt, className }: { src: string; alt?: string; className?: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let objUrl = ''
    let active = true
    api.get(src, { responseType: 'blob' }).then((r) => {
      if (!active) return
      objUrl = URL.createObjectURL(r.data)
      setUrl(objUrl)
    }).catch(() => {})
    return () => { active = false; if (objUrl) URL.revokeObjectURL(objUrl) }
  }, [src])
  if (!url) return <div className={`${className || ''} animate-pulse bg-white/10`} />
  return <img src={url} alt={alt} className={className} />
}
