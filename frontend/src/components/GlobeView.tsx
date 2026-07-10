import { useEffect, useRef, useMemo, useCallback } from 'react'
import Globe from 'react-globe.gl'
import type { WeatherForecast, WeatherSignal } from '../types'

interface Props {
  forecasts: WeatherForecast[]
  signals: WeatherSignal[]
}

interface CityMarker {
  lat: number
  lng: number
  name: string
  key: string
  forecast: WeatherForecast | null
  bestSignal: WeatherSignal | null
  hasActionable: boolean
}

const CITIES: Record<string, { lat: number; lng: number; name: string }> = {
  wuhan: { lat: 30.5928, lng: 114.3055, name: '武汉' },
  hongkong: { lat: 22.3193, lng: 114.1694, name: '香港' },
  shanghai: { lat: 31.2304, lng: 121.4737, name: '上海' },
  guangzhou: { lat: 23.1291, lng: 113.2644, name: '广州' },
  shenzhen: { lat: 22.5431, lng: 114.0579, name: '深圳' },
}

export function GlobeView({ forecasts, signals }: Props) {
  const globeRef = useRef<any>(null)

  const markers: CityMarker[] = useMemo(() => {
    return Object.entries(CITIES).map(([key, city]) => {
      const forecast = forecasts.find(f => f.city_key === key) || null
      const citySignals = signals.filter(s => s.city_key === key)
      const actionableSignals = citySignals.filter(s => s.actionable)
      const bestSignal = actionableSignals.length > 0
        ? actionableSignals.reduce((a, b) => Math.abs(a.edge) > Math.abs(b.edge) ? a : b)
        : citySignals.length > 0
          ? citySignals.reduce((a, b) => Math.abs(a.edge) > Math.abs(b.edge) ? a : b)
          : null

      return {
        lat: city.lat,
        lng: city.lng,
        name: city.name,
        key,
        forecast,
        bestSignal,
        hasActionable: actionableSignals.length > 0,
      }
    })
  }, [forecasts, signals])

  useEffect(() => {
    if (globeRef.current) {
      globeRef.current.pointOfView({ lat: 30, lng: 115, altitude: 2.2 }, 1000)
      globeRef.current.controls().autoRotate = true
      globeRef.current.controls().autoRotateSpeed = 0.3
      globeRef.current.controls().enableZoom = false
    }
  }, [])

  const handleInteraction = useCallback(() => {
    if (globeRef.current) {
      globeRef.current.controls().autoRotate = false
      setTimeout(() => {
        if (globeRef.current) {
          globeRef.current.controls().autoRotate = true
        }
      }, 5000)
    }
  }, [])

  const markerElement = useCallback((d: object) => {
    const marker = d as CityMarker
    const el = document.createElement('div')
    el.className = 'city-marker'

    const dotColor = marker.hasActionable ? '#22c55e' : marker.bestSignal ? '#d97706' : '#525252'

    const dot = document.createElement('div')
    dot.className = 'marker-dot'
    dot.style.backgroundColor = dotColor
    dot.style.color = dotColor
    el.appendChild(dot)

    const label = document.createElement('div')
    label.className = 'marker-label'

    const nameSpan = document.createElement('div')
    nameSpan.className = 'marker-name'
    nameSpan.textContent = marker.name
    label.appendChild(nameSpan)

    if (marker.forecast) {
      const tempSpan = document.createElement('div')
      tempSpan.className = 'marker-temp'
      tempSpan.style.color = '#e5e5e5'
      tempSpan.textContent = `${marker.forecast.mean_high.toFixed(0)}C`
      label.appendChild(tempSpan)
    }

    if (marker.bestSignal) {
      const edgeSpan = document.createElement('div')
      edgeSpan.className = 'marker-edge'
      const edgeVal = (marker.bestSignal.edge * 100).toFixed(1)
      edgeSpan.style.color = marker.bestSignal.edge > 0 ? '#22c55e' : '#dc2626'
      edgeSpan.textContent = `${marker.bestSignal.edge > 0 ? '+' : ''}${edgeVal}%`
      label.appendChild(edgeSpan)
    }

    el.appendChild(label)
    return el
  }, [])

  return (
    <div className="globe-container w-full h-full">
      <Globe
        ref={globeRef}
        globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
        backgroundColor="rgba(0,0,0,0)"
        atmosphereColor="#1a1a2e"
        atmosphereAltitude={0.15}
        htmlElementsData={markers}
        htmlElement={markerElement}
        htmlAltitude={0.01}
        onGlobeClick={handleInteraction}
        width={undefined}
        height={undefined}
      />
    </div>
  )
}
