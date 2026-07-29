export interface PhotoTip {
  exposure: string;
  filter: string;
  bestTimes: string;
  notes: string;
}

export interface PlanetData {
  name: string;
  nameDE: string;
  color: string;
  radius: number;
  semiMajorAxis: number;
  eccentricity: number;
  inclination: number;
  period: number;
  rotationPeriod: number;
  axialTilt: number;
  moons: number;
  atmosphere: string;
  temperature: string;
  mass: string;
  diameter: number;
  discovery: string;
  description: string;
  textureMap: string;
  realPhotoUrl?: string;
  photoTip?: PhotoTip;
}

export interface MoonData {
  name: string
  nameDE: string
  radius: number           // relative Größe (0.273 = 27% von Erde)
  semiMajorAxis: number    // Abstand zum Elternplanet in Scene-Units (z.B. 2.5)
  eccentricity: number
  inclination: number      // Grad
  period: number           // Umlaufzeit in Erdjahren (27.3 Tage = 0.0748)
  rotationPeriod: number   // Eigenrotation in Stunden (27.3 Tage = 655.7h, gebundene Rotation)
  textureMap: string
  color?: string
  description: string
  mass: string
  diameter: number
  temperature: string
  atmosphere: string
  realPhotoUrl?: string
  photoTip?: PhotoTip
}

export const SUN_DATA: PlanetData = {
  name: 'Sun',
  nameDE: 'Sonne',
  color: '#FDB813',
  radius: 109.2,
  semiMajorAxis: 0,
  eccentricity: 0,
  inclination: 0,
  period: 0,
  rotationPeriod: 609.12,
  axialTilt: 7.25,
  moons: 0,
  atmosphere: 'Wasserstoff (73 %), Helium (25 %)',
  temperature: '5.500 °C (Oberfläche), 15.000.000 °C (Kern)',
  mass: '333.000 Erdmassen',
  diameter: 1392700,
  discovery: 'Bekannt seit der Antike',
  description: 'Der Stern im Zentrum unseres Sonnensystems — eine Glatze aus heißem Plasma, die 99,86 % der Systemmasse enthält.',
  textureMap: '/textures/sun.jpg',
  realPhotoUrl: '/photos/sun-nasa-sdo-high-resolution-photo-1.jpg',
};

export const PLANETS: PlanetData[] = [
  {
    name: 'Mercury',
    nameDE: 'Merkur',
    color: '#A0A0A0',
    radius: 0.383,
    semiMajorAxis: 8,
    eccentricity: 0.2056,
    inclination: 7.0,
    period: 0.241,
    rotationPeriod: 1407.6,
    axialTilt: 0.034,
    moons: 0,
    atmosphere: 'Extrem dünn (O, Na, K)',
    temperature: '-173 bis 427 °C',
    mass: '0,055 Erdmassen',
    diameter: 4879,
    discovery: 'Bekannt seit der Antike',
    description: 'Der kleinste und sonnennächste Planet — eine karge, von Kratern bedeckte Wüste ohne nennenswerte Atmosphäre.',
    textureMap: '/textures/mercury.jpg',
    realPhotoUrl: '/photos/mercury-planet-true-color-nasa-messenger-1.jpg',
    photoTip: {
      exposure: '1/125s, ISO 200',
      filter: 'ND-Filter nötig',
      bestTimes: 'Abends kurz vor Sonnenuntergang',
      notes: 'Schwieriges Ziel — nie weit von der Sonne entfernt, daher nur in der Dämmerung sichtbar.',
    },
  },
  {
    name: 'Venus',
    nameDE: 'Venus',
    color: '#E8B86D',
    radius: 0.949,
    semiMajorAxis: 12,
    eccentricity: 0.0068,
    inclination: 3.39,
    period: 0.615,
    rotationPeriod: -5832.5,
    axialTilt: 177.4,
    moons: 0,
    atmosphere: 'CO₂ (96,5 %), N₂ (3,5 %)',
    temperature: '~462 °C',
    mass: '0,815 Erdmassen',
    diameter: 12104,
    discovery: 'Bekannt seit der Antike',
    description: 'Der heißeste Planet mit einer dichten CO₂-Atmosphäre und Schwefelsäurewolken — ein extremer Treibhauseffekt.',
    textureMap: '/textures/venus.jpg',
    realPhotoUrl: '/photos/venus-planet-true-color-nasa-mariner-pho-1.jpg',
    photoTip: {
      exposure: '1/250s, ISO 100',
      filter: 'UV-Filter empfohlen',
      bestTimes: 'Morgen- oder Abenddämmerung',
      notes: 'Sehr hell, oft als „Morgenstern“ oder „Abendstern“ bezeichnet. Phasen wie der Mond sichtbar.',
    },
  },
  {
    name: 'Earth',
    nameDE: 'Erde',
    color: '#4A90D9',
    radius: 1.0,
    semiMajorAxis: 16,
    eccentricity: 0.0167,
    inclination: 0.0,
    period: 1.0,
    rotationPeriod: 23.93,
    axialTilt: 23.44,
    moons: 1,
    atmosphere: 'N₂ (78 %), O₂ (21 %), Ar (1 %)',
    temperature: '-88 bis 58 °C',
    mass: '1,0 Erdmassen',
    diameter: 12742,
    discovery: 'Heimatplanet',
    description: 'Unser Heimatplanet — der einzige bekannte mit flüssigem Wasser und Leben. Blaue Ozeane, grüne Kontinente, weiße Wolken.',
    textureMap: '/textures/earth.jpg',
    realPhotoUrl: '/photos/earth-blue-marble-nasa-photo-1.jpg',
    photoTip: {
      exposure: '1/60s, ISO 400',
      filter: 'Polarisationsfilter',
      bestTimes: 'Blauen Stunde',
      notes: 'Aus dem All: „Blue Marble“. Von der Erde aus: ISS-Transits sind ein Highlight.',
    },
  },
  {
    name: 'Mars',
    nameDE: 'Mars',
    color: '#CD5C5C',
    radius: 0.532,
    semiMajorAxis: 22,
    eccentricity: 0.0934,
    inclination: 1.85,
    period: 1.881,
    rotationPeriod: 24.62,
    axialTilt: 25.19,
    moons: 2,
    atmosphere: 'CO₂ (95 %), N₂ (3 %), Ar (1,6 %)',
    temperature: '-153 bis 20 °C',
    mass: '0,107 Erdmassen',
    diameter: 6779,
    discovery: 'Bekannt seit der Antike',
    description: 'Der rote Planet — eisige Wüsten, der größte Vulkan des Sonnensystems und Spuren von einstigem flüssigem Wasser.',
    textureMap: '/textures/mars.jpg',
    realPhotoUrl: '/photos/mars-planet-surface-nasa-high-resolution-2.jpg',
    photoTip: {
      exposure: '1/60s, ISO 800',
      filter: 'Roter Filter (Wratten #25)',
      bestTimes: 'Opposition (alle ~2 Jahre)',
      notes: 'Oberflächenmerkmale wie Polkappen und Syrtis Major sind bei Opposition erkennbar.',
    },
  },
  {
    name: 'Jupiter',
    nameDE: 'Jupiter',
    color: '#D8A47F',
    radius: 11.21,
    semiMajorAxis: 40,
    eccentricity: 0.0489,
    inclination: 1.31,
    period: 11.862,
    rotationPeriod: 9.93,
    axialTilt: 3.13,
    moons: 95,
    atmosphere: 'H₂ (90 %), He (10 %)',
    temperature: '~-145 °C',
    mass: '317,8 Erdmassen',
    diameter: 139820,
    discovery: 'Bekannt seit der Antike',
    description: 'Der größte Planet — ein Gasriese mit dem Großen Roten Fleck, einem Sturm, der seit Jahrhunderten wütet.',
    textureMap: '/textures/jupiter.jpg',
    realPhotoUrl: '/photos/jupiter-planet-nasa-juno-photo-1.jpg',
    photoTip: {
      exposure: '1/125s, ISO 1600',
      filter: 'Keiner notwendig',
      bestTimes: 'Opposition (jährlich)',
      notes: 'Bänderstrukturen und die vier Galileischen Monde sind bereits im Fernglas sichtbar.',
    },
  },
  {
    name: 'Saturn',
    nameDE: 'Saturn',
    color: '#E3D9A8',
    radius: 9.45,
    semiMajorAxis: 60,
    eccentricity: 0.0565,
    inclination: 2.49,
    period: 29.457,
    rotationPeriod: 10.66,
    axialTilt: 26.73,
    moons: 146,
    atmosphere: 'H₂ (96 %), He (3 %)',
    temperature: '~-178 °C',
    mass: '95,2 Erdmassen',
    diameter: 116460,
    discovery: 'Bekannt seit der Antike',
    description: 'Der Ringplanet — ein Gasriese mit spektakulären Ringsystemen aus Eis und Gestein, die Tausende von Ringen bilden.',
    textureMap: '/textures/saturn.png',
    realPhotoUrl: '/photos/saturn-planet-nasa-cassini-photo-1.jpg',
    photoTip: {
      exposure: '1/60s, ISO 3200',
      filter: 'Gelber Filter (Wratten #8)',
      bestTimes: 'Opposition (jährlich)',
      notes: 'Ringe sind im Teleskop ab 30-facher Vergrößerung erkennbar. Cassini-Teilung bei guter Optik sichtbar.',
    },
  },
  {
    name: 'Uranus',
    nameDE: 'Uranus',
    color: '#AFDBF5',
    radius: 4.01,
    semiMajorAxis: 85,
    eccentricity: 0.0457,
    inclination: 0.77,
    period: 84.011,
    rotationPeriod: -17.24,
    axialTilt: 97.77,
    moons: 28,
    atmosphere: 'H₂ (83 %), He (15 %), CH₄ (2 %)',
    temperature: '~-224 °C',
    mass: '14,5 Erdmassen',
    diameter: 50724,
    discovery: 'William Herschel, 1781',
    description: 'Der Eisriese, der auf der Seite rollt — seine Rotationsachse liegt fast in der Bahnebene, was extreme Jahreszeiten erzeugt.',
    textureMap: '/textures/uranus.jpg',
    realPhotoUrl: '/photos/uranus-planet-nasa-voyager-photo-1.jpg',
    photoTip: {
      exposure: '1/15s, ISO 6400',
      filter: 'Grüner Filter',
      bestTimes: 'Opposition (jährlich)',
      notes: 'Sehr klein und blass — benötigt mindestens 100 mm Öffnung. Methan absorbiert rotes Licht, daher bläulich.',
    },
  },
  {
    name: 'Neptune',
    nameDE: 'Neptun',
    color: '#4166F5',
    radius: 3.88,
    semiMajorAxis: 110,
    eccentricity: 0.0113,
    inclination: 1.77,
    period: 164.79,
    rotationPeriod: 16.11,
    axialTilt: 28.32,
    moons: 16,
    atmosphere: 'H₂ (80 %), He (19 %), CH₄ (1 %)',
    temperature: '~-214 °C',
    mass: '17,1 Erdmassen',
    diameter: 49244,
    discovery: 'Johann Galle, 1846 (berechnet von Le Verrier)',
    description: 'Der äußerste Planet — ein stürmischer Eisriese mit den stärksten Winden des Sonnensystems (bis 2.100 km/h).',
    textureMap: '/textures/neptune-planet-surface-texture-map-2k-eq-1.jpg',
    realPhotoUrl: '/photos/neptune-planet-nasa-voyager-photo-1.jpg',
    photoTip: {
      exposure: '1/8s, ISO 6400',
      filter: 'Blaue Filter',
      bestTimes: 'Opposition (jährlich)',
      notes: 'Sehr lichtschwach — mindestens 200 mm Öffnung nötig. Großer Dunkler Fleck gelegentlich sichtbar.',
    },
  },
];

export const EARTH_MOONS: MoonData[] = [
  {
    name: 'Moon',
    nameDE: 'Erdenmond',
    radius: 0.273,
    semiMajorAxis: 2.5,
    eccentricity: 0.0549,
    inclination: 5.145,
    period: 0.0748,       // 27.32 Tage / 365.25
    rotationPeriod: 655.7, // 27.32 Tage × 24h (gebundene Rotation)
    textureMap: '/textures/moon-surface-texture-map-2k-equirectangu-1.jpg',
    color: '#cccccc',
    description: 'Unser ständiger Begleiter — der größte und hellste Himmelskörper am Nachthimmel. Die Oberfläche ist von Kratern, Ebenen (Maria) und Gebirgen geprägt.',
    mass: '0,0123 Erdmassen',
    diameter: 3474,
    temperature: '-173 bis 127 °C',
    atmosphere: 'Keine (Exosphäre aus He, Ne, Ar)',
    realPhotoUrl: '/photos/earth-s-moon-full-disk-nasa-photo-high-r-1.jpg',
    photoTip: {
      exposure: '1/125s, ISO 200',
      filter: 'Keiner notwendig',
      bestTimes: 'Vollmond, Opposition',
      notes: 'Leichtestes Himmelsobjekt nach der Sonne. Erdlicht (aschgraue Mondphasen) lohnt sich besonders.',
    },
  },
]