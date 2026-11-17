/**
 * rooms.ts - the office's rooms: where the doors, desks, seats and walking routes are.
 *
 * Five places in a star. The corridor is the hub: the office's one door leads
 * to it and every other room has one door onto it, so any room change is
 * "own door -> corridor -> their door" (findRoomPath). People join and leave
 * the building through the corridor's front door.
 *
 *   main-office    desk work (the only room with art today)
 *   corridor       the hub; front door / lift; the manager's nameplate door is
 *                  decoration only (no room behind it, the boss sits in the office)
 *   meeting-room   a session's agents when it runs several at once or waits on you
 *   server-room    MCP server workers
 *   lunch-room     long-idle agents and coffee / water breaks
 *
 * Which room an agent belongs in is decided in src/roomRules.ts; whether a
 * room can be used at all (its art exists, or ?rooms=all) in src/roomAccess.ts;
 * the walk between rooms in src/roomTransfer.ts.
 *
 * Positions are percentages (0-100) of the room picture (1508 x 1126 art,
 * the 4800 x 3584 aspect). Every room is the same isometric box, drawn by
 * editing the office's picture, so the four new rooms' layouts were computed
 * on each room's measured floor corners (back, right, front, left) and can be
 * fine-tuned with /?helper&room=<id> (docs/reference.md, "Rooms").
 */

export type RoomId =
  | 'main-office'
  | 'corridor'
  | 'meeting-room'
  | 'server-room'
  | 'lunch-room'
  // Floor 2 — the business team, on the same art as the rooms above (docs/hermes-office/ROOMS.md)
  | 'business-suite'
  | 'creative-studio'
  | 'finance-legal'
  | 'exec-floor'

export interface Waypoint {
  id: string
  x: number  // percentage
  y: number
  connections: string[]  // ids of connected waypoints
}

export interface FurnitureItem {
  id: string
  type: string        // e.g. 'desk-dual', 'chair-aeron', 'plant-monstera'
  sprite: string      // sprite sheet + frame reference
  x: number           // percentage position within room (0-100)
  y: number
  zIndex?: number
  state?: string      // e.g. 'empty', 'occupied', 'brewing'
  interactive?: boolean
  label?: string
}

export type SpriteFacing = 'front-left' | 'front-right' | 'rear-left' | 'rear-right'

export interface RoomConnection {
  toRoom: RoomId
  position: { x: number; y: number }  // door/exit position in current room (%)
  label?: string
  exitFacing?: SpriteFacing   // agent direction when leaving through this door
  entryFacing?: SpriteFacing  // agent direction when arriving through this door
  /**
   * The door itself in the room's picture (% of the stage, top-left corner and
   * size), so clicking it shows the room it leads to (src/components/DoorLinks.tsx).
   * Measured on the day art; the Dunder Mifflin copies have their doors in the same place.
   */
  door?: { x: number; y: number; w: number; h: number }
}

export interface AgentSpot {
  id: string
  type: 'desk' | 'meeting-seat' | 'lounge' | 'standing' | 'water' | 'coffee' | 'filing' | 'printer' | 'door'
  x: number
  y: number
  facing?: 'up' | 'down' | 'left' | 'right'
  spriteFacing?: SpriteFacing  // which direction the agent faces when at this spot
  zIndex?: number  // explicit z-index override (for agents behind desks)
}

/**
 * Something the room's picture shows that is not a way into another room:
 * the corridor's front door (where people join and leave the building) and
 * the manager's nameplate door (decoration; nobody walks through it).
 */
export interface RoomLandmark {
  id: string
  kind: 'front-door' | 'decor-door'
  label: string
  x: number
  y: number
}

export interface Room {
  id: RoomId
  name: string
  description: string
  /** Which floor the floor plan puts it on: 1 (default) is the office's own floor */
  floor?: 1 | 2
  /** The room whose art this one borrows, so a floor-2 room needs no new artwork */
  artReuse?: RoomId
  background: {
    day: string       // path to empty room background
    night: string
  }
  /** The same two pictures for the Dunder Mifflin theme (the office's own live in src/theme.ts) */
  backgroundDm?: {
    day: string
    night: string
  }
  width: number       // room dimensions in px (rendered)
  height: number
  furniture: FurnitureItem[]
  connections: RoomConnection[]
  agentSpots: AgentSpot[]       // where agents can sit/stand/work
  entryPoint: { x: number; y: number }  // where agents appear when entering
  walkableArea?: { x: number; y: number }[]  // polygon defining where agents can walk
  ambience?: string   // ambient sound loop
  waypoints?: Waypoint[]  // named walkable nodes for pathfinding
  /** Doors and the like that lead nowhere in the model (see RoomLandmark) */
  landmarks?: RoomLandmark[]
  /** true while the layout was placed without art: re-place it with /?helper when the art lands */
  provisional?: boolean
}

/** The room every other room opens onto */
export const HUB_ROOM: RoomId = 'corridor'
/** Where everyone has a desk; the room shown by default */
export const OFFICE_ROOM: RoomId = 'main-office'

// ===== ROOM DEFINITIONS =====

export const ROOMS: Record<RoomId, Room> = {
  'main-office': {
    id: 'main-office',
    name: 'Main Office',
    description: 'Open plan workspace where agents code, debug, and ship',
    background: {
      day: '/rooms/office-day.png',
      night: '/rooms/office-night.png',
    },
    width: 800,
    height: 600,
    furniture: [
      // Desk cluster - back
      { id: 'desk-1a', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 42.4, y: 50.4 },
      { id: 'desk-1b', type: 'desk-standing', sprite: 'desk-standing-left-front', x: 46.7, y: 53 },
      { id: 'desk-1c', type: 'desk-standing', sprite: 'desk-standing-right-front', x: 39.9, y: 55.2 },
      // Desk cluster - front left
      { id: 'desk-2a', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 31.4, y: 64.8 },
      { id: 'desk-2b', type: 'desk-standing', sprite: 'desk-standing-left-front', x: 35.4, y: 67.5 },
      { id: 'desk-2c', type: 'desk-standing', sprite: 'desk-standing-right-front', x: 27.9, y: 70 },
      // Desk cluster - right
      { id: 'desk-3a', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 59, y: 73.7 },
      { id: 'desk-3b', type: 'desk-standing', sprite: 'desk-standing-left-front', x: 62.6, y: 76 },
      { id: 'desk-3c', type: 'desk-standing', sprite: 'desk-standing-right-front', x: 55.4, y: 78.7 },
      { id: 'desk-3d', type: 'desk-standing', sprite: 'desk-standing-right-rear', x: 66.6, y: 71.1 },
      // Coffee machine on counter
      { id: 'coffee', type: 'coffee-machine', sprite: 'coffee-off', x: 78.5, y: 50.2, interactive: true, state: 'off', label: 'Coffee Machine' },
      // Filing cabinet
      { id: 'filing-1', type: 'filing-cabinet', sprite: 'filing-closed', x: 45, y: 56.5, state: 'closed', label: 'Filing Cabinet' },
      // Plants
      { id: 'plant-1', type: 'plant-monstera', sprite: 'plant-monstera', x: 91.9, y: 64.7 },
      { id: 'plant-2', type: 'plant-snake', sprite: 'plant-snake', x: 43.2, y: 37.9 },
      { id: 'plant-3', type: 'plant-money', sprite: 'plant-money', x: 32, y: 71.2 },
      { id: 'plant-4', type: 'plant-money', sprite: 'plant-money', x: 89.2, y: 65.7 },
      { id: 'plant-5', type: 'plant-monstera', sprite: 'plant-monstera', x: 60.2, y: 80.4 },
      // Printer (swaps between working/broken on printer jam event)
      { id: 'printer-1', type: 'printer', sprite: 'printer-working', x: 85.4, y: 56.8, state: 'working', label: 'Printer' },
      // Background hotspots — baked into the room image, no sprite, just clickable zones
      { id: 'fire-extinguisher', type: 'hotspot', sprite: 'hotspot', x: 8, y: 60, interactive: true, label: 'Fire Extinguisher' },
      { id: 'water-cooler', type: 'hotspot', sprite: 'hotspot', x: 53, y: 45, interactive: true, label: 'Water Cooler' },
      { id: 'bell', type: 'hotspot', sprite: 'hotspot', x: 63, y: 39, interactive: true, label: 'Bell' },
      { id: 'kanban-board', type: 'hotspot', sprite: 'hotspot', x: 80, y: 42, interactive: true, label: 'Kanban Board' },
      { id: 'ship-it-poster', type: 'hotspot', sprite: 'hotspot', x: 8, y: 45, interactive: true, label: 'Ship It Poster' },
      { id: 'tv-monitor', type: 'hotspot', sprite: 'hotspot', x: 90, y: 42, interactive: true, label: 'Dashboard' },
    ],
    connections: [
      // The office's one door: it leads to the corridor, and through it to every other room
      { toRoom: 'corridor', position: { x: 67.5, y: 48.9 }, label: 'Corridor', exitFacing: 'rear-right', entryFacing: 'front-right', door: { x: 64.8, y: 21.8, w: 7.7, h: 27.3 } },
    ],
    agentSpots: [
      // Desk spots
      // In front of desk: rear-left/rear-right (z higher than desk)
      // Behind desk: front-left/front-right (z lower than desk)
      // Front-left cluster: desks at y ~65-70
      { id: 'spot-1', type: 'desk', x: 25.8, y: 71, facing: 'down', spriteFacing: 'rear-left', zIndex: 85 },
      { id: 'spot-2', type: 'desk', x: 37.9, y: 68.2, facing: 'down', spriteFacing: 'rear-right', zIndex: 85 },
      { id: 'spot-3', type: 'desk', x: 26.9, y: 59.2, facing: 'down', spriteFacing: 'front-left', zIndex: 40 },
      // Back cluster: desks at y ~50-55
      { id: 'spot-4', type: 'desk', x: 38.5, y: 55.2, facing: 'down', spriteFacing: 'rear-left', zIndex: 58 },
      { id: 'spot-5', type: 'desk', x: 48.9, y: 52.9, facing: 'down', spriteFacing: 'rear-right', zIndex: 70 },
      { id: 'spot-6', type: 'desk', x: 38.8, y: 43.6, facing: 'down', spriteFacing: 'front-left', zIndex: 30 },
      // Right cluster: desks at y ~72-79
      { id: 'spot-7', type: 'desk', x: 52.7, y: 78.8, facing: 'down', spriteFacing: 'rear-left', zIndex: 95 },
      { id: 'spot-8', type: 'desk', x: 65.9, y: 75.8, facing: 'down', spriteFacing: 'rear-right', zIndex: 95 },
      { id: 'spot-9', type: 'desk', x: 55.2, y: 66.8, facing: 'down', spriteFacing: 'front-left', zIndex: 55 },
      { id: 'spot-10', type: 'desk', x: 68.7, y: 66.2, facing: 'down', spriteFacing: 'front-right', zIndex: 55 },
      // Activity spots
      { id: 'spot-coffee-1', type: 'coffee', x: 73.5, y: 56.7, facing: 'down', spriteFacing: 'rear-left' },
      { id: 'spot-coffee-2', type: 'coffee', x: 76.2, y: 58.4, facing: 'down', spriteFacing: 'front-right' },
      { id: 'spot-water-1', type: 'water', x: 53.3, y: 46.6, facing: 'down', spriteFacing: 'rear-left' },
      { id: 'spot-water-2', type: 'water', x: 56, y: 47.7, facing: 'down', spriteFacing: 'front-right' },
      { id: 'spot-filing', type: 'filing', x: 47.8, y: 57.6, facing: 'down', spriteFacing: 'front-right', zIndex: 70 },
      { id: 'spot-printer', type: 'printer', x: 81, y: 63, facing: 'down', spriteFacing: 'rear-left' },
      { id: 'spot-door-2', type: 'door', x: 64, y: 46.6, facing: 'down', spriteFacing: 'rear-right' },
      { id: 'spot-door-3', type: 'door', x: 69.9, y: 50.8, facing: 'down', spriteFacing: 'front-right' },

      // Community: three desks of their own, right of the dev clusters
      { id: 'biz-m1', type: 'desk', x: 74.5, y: 63.5, facing: 'down', spriteFacing: 'front-left', zIndex: 62 },
      { id: 'biz-m2', type: 'desk', x: 79.0, y: 60.0, facing: 'down', spriteFacing: 'front-left', zIndex: 60 },
      { id: 'biz-m3', type: 'desk', x: 83.0, y: 57.0, facing: 'down', spriteFacing: 'front-left', zIndex: 58 },
    ],
    entryPoint: { x: 67.5, y: 48.9 },
    walkableArea: [
      { x: 28.2, y: 46 },
      { x: 33, y: 50.2 },
      { x: 20.6, y: 60.9 },
      { x: 21.8, y: 65.5 },
      { x: 32, y: 71.4 },
      { x: 41.6, y: 62.7 },
      { x: 40.8, y: 58.1 },
      { x: 45.5, y: 56.3 },
      { x: 49.3, y: 54.5 },
      { x: 51.3, y: 52.2 },
      { x: 51.9, y: 49.3 },
      { x: 51.5, y: 46.7 },
      { x: 57.9, y: 47.3 },
      { x: 64.2, y: 47.4 },
      { x: 70, y: 49.9 },
      { x: 71.2, y: 55.4 },
      { x: 78.8, y: 60.7 },
      { x: 86.7, y: 65.6 },
      { x: 82.6, y: 72.8 },
      { x: 71.5, y: 68.4 },
      { x: 59.5, y: 57.1 },
      { x: 54.7, y: 61.9 },
      { x: 51.4, y: 65.9 },
      { x: 49.8, y: 70.1 },
      { x: 50, y: 75.3 },
      { x: 54.3, y: 78.2 },
      { x: 58.1, y: 80 },
      { x: 62.5, y: 78.9 },
      { x: 64.9, y: 76 },
      { x: 68.4, y: 73.3 },
      { x: 70.4, y: 71.1 },
      { x: 71.7, y: 69.3 },
      { x: 82.7, y: 73.4 },
      { x: 54.3, y: 93.6 },
      { x: 37.6, y: 84 },
      { x: 23.5, y: 75.6 },
      { x: 12.6, y: 68.8 },
      { x: 3.9, y: 62.9 },
      { x: 33.7, y: 42.4 },
      { x: 35.5, y: 48.6 },
      { x: 33, y: 50.2 },
      { x: 28.7, y: 46.3 },
    ],
    waypoints: [
      // User-mapped routes from /?helper — spots + aisle junctions
      { id: 'W-door',      x: 67.5, y: 48.9, connections: ['W-door-2', 'W-door-3'] },
      { id: 'W-door-2',    x: 64,   y: 46.6, connections: ['W-door', 'W-water-1', 'W-new-6'] },
      { id: 'W-door-3',    x: 69.9, y: 50.8, connections: ['W-door', 'W-coffee-1', 'W-spot-10', 'W-new-7'] },
      { id: 'W-water-1',   x: 53.3, y: 46.6, connections: ['W-door-2', 'W-water-2', 'W-spot-5'] },
      { id: 'W-water-2',   x: 56,   y: 47.7, connections: ['W-water-1', 'W-door-2', 'W-new-10'] },
      { id: 'W-spot-6',    x: 38.8, y: 43.6, connections: ['W-spot-4', 'W-water-1'] },
      { id: 'W-spot-4',    x: 38.5, y: 55.2, connections: ['W-spot-6', 'W-spot-5', 'W-spot-3', 'W-filing', 'W-new-19'] },
      { id: 'W-spot-5',    x: 48.9, y: 52.9, connections: ['W-spot-4', 'W-water-1', 'W-filing', 'W-spot-9'] },
      { id: 'W-filing',    x: 47.8, y: 57.6, connections: ['W-spot-4', 'W-spot-5', 'W-spot-9', 'W-new-4'] },
      { id: 'W-spot-3',    x: 26.9, y: 59.2, connections: ['W-spot-4', 'W-spot-1'] },
      { id: 'W-spot-1',    x: 25.8, y: 71,   connections: ['W-spot-3', 'W-spot-2', 'W-new-12'] },
      { id: 'W-spot-2',    x: 37.9, y: 68.2, connections: ['W-spot-1', 'W-spot-4', 'W-spot-7', 'W-new-2'] },
      { id: 'W-spot-9',    x: 55.2, y: 66.8, connections: ['W-filing', 'W-spot-5', 'W-spot-7', 'W-spot-10'] },
      { id: 'W-spot-10',   x: 68.7, y: 66.2, connections: ['W-spot-9', 'W-spot-8', 'W-door-3', 'W-coffee-1', 'W-biz-m1', 'W-biz-m2', 'W-biz-m3'] },
      { id: 'W-spot-7',    x: 52.7, y: 78.8, connections: ['W-spot-9', 'W-spot-2', 'W-spot-8'] },
      { id: 'W-spot-8',    x: 65.9, y: 75.8, connections: ['W-spot-7', 'W-spot-10', 'W-new-22'] },
      { id: 'W-coffee-1',  x: 73.5, y: 56.7, connections: ['W-door-3', 'W-coffee-2', 'W-spot-10'] },
      { id: 'W-coffee-2',  x: 76.2, y: 58.4, connections: ['W-coffee-1', 'W-printer'] },
      { id: 'W-printer',   x: 81,   y: 63,   connections: ['W-coffee-2', 'W-new-23'] },
      // Aisle junctions
      { id: 'W-new-1',     x: 44.8, y: 63.1, connections: ['W-new-3'] },
      { id: 'W-new-2',     x: 57.5, y: 51.6, connections: ['W-spot-2', 'W-new-5'] },
      { id: 'W-new-3',     x: 37.5, y: 67.6, connections: ['W-new-1'] },
      { id: 'W-new-4',     x: 44.3, y: 63.3, connections: ['W-filing', 'W-new-14'] },
      { id: 'W-new-5',     x: 47.4, y: 58.3, connections: ['W-new-2'] },
      { id: 'W-new-6',     x: 57,   y: 52.2, connections: ['W-door-2', 'W-new-8'] },
      { id: 'W-new-7',     x: 63.9, y: 46.8, connections: ['W-door-3'] },
      { id: 'W-new-8',     x: 68.5, y: 49.9, connections: ['W-new-6'] },
      { id: 'W-new-10',    x: 55.6, y: 49.2, connections: ['W-water-2'] },
      { id: 'W-new-12',    x: 36.3, y: 76.8, connections: ['W-spot-1', 'W-new-13'] },
      { id: 'W-new-13',    x: 25.8, y: 72.2, connections: ['W-new-12', 'W-new-16'] },
      { id: 'W-new-14',    x: 36.9, y: 76.7, connections: ['W-new-4'] },
      { id: 'W-new-16',    x: 18.5, y: 59.5, connections: ['W-new-13', 'W-new-18'] },
      { id: 'W-new-18',    x: 29.9, y: 47.1, connections: ['W-new-16', 'W-new-20'] },
      { id: 'W-new-19',    x: 18.3, y: 57.7, connections: ['W-spot-4'] },
      { id: 'W-new-20',    x: 38.8, y: 54.2, connections: ['W-new-18'] },
      { id: 'W-new-22',    x: 76.3, y: 70.5, connections: ['W-spot-8', 'W-new-24'] },
      { id: 'W-new-23',    x: 66.8, y: 75.6, connections: ['W-printer'] },
      { id: 'W-new-24',    x: 81.3, y: 62.5, connections: ['W-new-22'] },

      // Community: beside the right-hand dev cluster, off the coffee corner
      { id: 'W-biz-m1', x: 74.5, y: 63.5, connections: ['W-spot-10'] },
      { id: 'W-biz-m2', x: 79.0, y: 60.0, connections: ['W-spot-10'] },
      { id: 'W-biz-m3', x: 83.0, y: 57.0, connections: ['W-spot-10'] },
    ],
  },

  // A hallway in the office's isometric box. Left wall: the lift (where people
  // join and leave the building) and the meeting room. Right wall, from the
  // corner: the manager's nameplate door (decoration), the server room, the
  // lunch room and the office. Nobody is stationed here: it is only walked through.
  'corridor': {
    id: 'corridor',
    name: 'Corridor',
    description: 'The hallway every room opens onto. In by the lift, out the same way.',
    background: {
      day: '/rooms/corridor-day.webp',
      night: '/rooms/corridor-night.webp',
    },
    backgroundDm: {
      day: '/rooms/corridor-day-dm.webp',
      night: '/rooms/corridor-night-dm.webp',
    },
    width: 800,
    height: 600,
    furniture: [],
    connections: [
      { toRoom: 'main-office', position: { x: 86.4, y: 66 }, label: 'Office', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 83.2, y: 36.8, w: 9.1, h: 30.2 } },
      { toRoom: 'meeting-room', position: { x: 31, y: 51.5 }, label: 'Meeting Room', exitFacing: 'rear-left', entryFacing: 'front-right', door: { x: 25, y: 22.9, w: 9, h: 28.4 } },
      { toRoom: 'server-room', position: { x: 62.3, y: 54 }, label: 'Server Room', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 58.8, y: 23.8, w: 8.9, h: 29.8 } },
      { toRoom: 'lunch-room', position: { x: 74.2, y: 59.3 }, label: 'Lunch Room', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 70.8, y: 30.4, w: 9, h: 28.2 } },
      // Floor 2: a lift bank between the meeting room's door and the manager's
      // nameplate — four small panels, so the walk stays "own door -> corridor
      // -> their door" without drawing four full doors on one wall.
      { toRoom: 'business-suite', position: { x: 36.0, y: 51.5 }, label: 'Business Suite (lift)', exitFacing: 'rear-left', entryFacing: 'front-right', door: { x: 34.4, y: 45.5, w: 3.2, h: 6.0 } },
      { toRoom: 'creative-studio', position: { x: 40.0, y: 51.5 }, label: 'Creative Studio (lift)', exitFacing: 'rear-left', entryFacing: 'front-right', door: { x: 38.4, y: 45.5, w: 3.2, h: 6.0 } },
      { toRoom: 'finance-legal', position: { x: 44.0, y: 51.5 }, label: 'Finance & Legal (lift)', exitFacing: 'rear-left', entryFacing: 'front-right', door: { x: 42.4, y: 45.5, w: 3.2, h: 6.0 } },
      { toRoom: 'exec-floor', position: { x: 48.0, y: 51.5 }, label: 'Exec Floor (lift)', exitFacing: 'rear-left', entryFacing: 'front-right', door: { x: 46.4, y: 45.5, w: 3.2, h: 6.0 } },
    ],
    landmarks: [
      { id: 'front-door', kind: 'front-door', label: 'Lift', x: 14.5, y: 63 },
      { id: 'manager-door', kind: 'decor-door', label: 'Manager', x: 51.2, y: 45.5 },
    ],
    agentSpots: [],
    // The lift: where newcomers appear and leavers are last seen
    entryPoint: { x: 14.5, y: 63 },
    walkableArea: [{ x: 43.6, y: 42.0 }, { x: 93.0, y: 67.6 }, { x: 53.7, y: 94.6 }, { x: 5.9, y: 65.5 }],
    waypoints: [
      { id: 'W-corr-lift', x: 14.5, y: 63.0, connections: ['W-corr-hub', 'W-corr-meeting'] },
      { id: 'W-corr-meeting', x: 31.0, y: 51.5, connections: ['W-corr-hub', 'W-corr-lift'] },
      { id: 'W-corr-hub', x: 50.5, y: 63.3, connections: ['W-corr-lift', 'W-corr-lunch', 'W-corr-meeting', 'W-corr-server', 'W-corr-floor2'] },
      { id: 'W-corr-server', x: 62.3, y: 54.0, connections: ['W-corr-hub', 'W-corr-lunch'] },
      { id: 'W-corr-lunch', x: 74.2, y: 59.3, connections: ['W-corr-hub', 'W-corr-office', 'W-corr-server'] },
      { id: 'W-corr-office', x: 86.4, y: 66.0, connections: ['W-corr-lunch'] },
      // The lift landing: one junction for the four floor-2 doors
      { id: 'W-corr-floor2', x: 51.8, y: 60.4, connections: ['W-corr-hub', 'W-corr-biz', 'W-corr-creative', 'W-corr-finance', 'W-corr-exec'] },
      { id: 'W-corr-biz', x: 36.0, y: 51.5, connections: ['W-corr-floor2'] },
      { id: 'W-corr-creative', x: 40.0, y: 51.5, connections: ['W-corr-floor2'] },
      { id: 'W-corr-finance', x: 44.0, y: 51.5, connections: ['W-corr-floor2'] },
      { id: 'W-corr-exec', x: 48.0, y: 51.5, connections: ['W-corr-floor2'] },
    ],
  },

  // One long table parallel to the window wall: four seats on the far side
  // (facing us, drawn behind the table) and four on the near side (backs to us).
  // Eight seats: a session's Claude and seven workers; more stay at their desks.
  'meeting-room': {
    id: 'meeting-room',
    name: 'Meeting Room',
    description: 'Where a session gathers when it runs several agents at once, or waits on you.',
    background: {
      day: '/rooms/meeting-room-day.webp',
      night: '/rooms/meeting-room-night.webp',
    },
    backgroundDm: {
      day: '/rooms/meeting-room-day-dm.webp',
      night: '/rooms/meeting-room-night-dm.webp',
    },
    width: 800,
    height: 600,
    furniture: [
      { id: 'meet-table', type: 'meeting-table', sprite: 'meeting-table', x: 47.9, y: 74.3, zIndex: 50 },
      { id: 'meet-whiteboard', type: 'whiteboard', sprite: 'whiteboard-mobile', x: 42.4, y: 44.5, zIndex: 31 },
      { id: 'meet-chair-1', type: 'meeting-chair', sprite: 'meeting-chair-front-right', x: 32.8, y: 63.9, zIndex: 30 },
      { id: 'meet-chair-2', type: 'meeting-chair', sprite: 'meeting-chair-front-right', x: 38.1, y: 60.2, zIndex: 31 },
      { id: 'meet-chair-3', type: 'meeting-chair', sprite: 'meeting-chair-front-right', x: 43.4, y: 56.6, zIndex: 32 },
      { id: 'meet-chair-4', type: 'meeting-chair', sprite: 'meeting-chair-front-right', x: 48.7, y: 53.0, zIndex: 33 },
      { id: 'meet-chair-5', type: 'meeting-chair', sprite: 'meeting-chair-rear-left', x: 46.8, y: 75.0, zIndex: 70 },
      { id: 'meet-chair-6', type: 'meeting-chair', sprite: 'meeting-chair-rear-left', x: 52.3, y: 71.2, zIndex: 71 },
      { id: 'meet-chair-7', type: 'meeting-chair', sprite: 'meeting-chair-rear-left', x: 57.8, y: 67.3, zIndex: 72 },
      { id: 'meet-chair-8', type: 'meeting-chair', sprite: 'meeting-chair-rear-left', x: 63.3, y: 63.5, zIndex: 73 },
    ],
    connections: [
      { toRoom: 'corridor', position: { x: 68, y: 51.5 }, label: 'Corridor', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 64.8, y: 21.8, w: 8.4, h: 28.4 } },
    ],
    agentSpots: [
      { id: 'meet-1', type: 'meeting-seat', x: 33.3, y: 64.4, facing: 'down', spriteFacing: 'front-right', zIndex: 40 },
      { id: 'meet-2', type: 'meeting-seat', x: 38.6, y: 60.8, facing: 'down', spriteFacing: 'front-right', zIndex: 41 },
      { id: 'meet-3', type: 'meeting-seat', x: 43.9, y: 57.1, facing: 'down', spriteFacing: 'front-right', zIndex: 42 },
      { id: 'meet-4', type: 'meeting-seat', x: 49.2, y: 53.5, facing: 'down', spriteFacing: 'front-right', zIndex: 43 },
      { id: 'meet-5', type: 'meeting-seat', x: 46.5, y: 74.1, facing: 'up', spriteFacing: 'rear-left', zIndex: 60 },
      { id: 'meet-6', type: 'meeting-seat', x: 52.0, y: 70.3, facing: 'up', spriteFacing: 'rear-left', zIndex: 61 },
      { id: 'meet-7', type: 'meeting-seat', x: 57.5, y: 66.5, facing: 'up', spriteFacing: 'rear-left', zIndex: 62 },
      { id: 'meet-8', type: 'meeting-seat', x: 63.0, y: 62.6, facing: 'up', spriteFacing: 'rear-left', zIndex: 63 },
    ],
    entryPoint: { x: 68, y: 51.5 },
    walkableArea: [{ x: 43.8, y: 37.0 }, { x: 93.0, y: 63.9 }, { x: 53.7, y: 93.1 }, { x: 5.9, y: 63.4 }],
    waypoints: [
      { id: 'W-meet-door', x: 68.0, y: 51.5, connections: ['W-meet-in'] },
      { id: 'W-meet-in', x: 67.3, y: 54.5, connections: ['W-meet-8', 'W-meet-door', 'W-meet-far-1', 'W-meet-near-1'] },
      { id: 'W-meet-far-1', x: 45.8, y: 46.7, connections: ['W-meet-4', 'W-meet-far-2', 'W-meet-in'] },
      { id: 'W-meet-far-2', x: 33.6, y: 55.3, connections: ['W-meet-1', 'W-meet-2', 'W-meet-3', 'W-meet-far-1', 'W-meet-far-3'] },
      { id: 'W-meet-far-3', x: 21.5, y: 63.9, connections: ['W-meet-end', 'W-meet-far-2'] },
      { id: 'W-meet-near-1', x: 75.0, y: 65.7, connections: ['W-meet-in', 'W-meet-near-2'] },
      { id: 'W-meet-near-2', x: 63.8, y: 74.0, connections: ['W-meet-7', 'W-meet-near-1', 'W-meet-near-3'] },
      { id: 'W-meet-near-3', x: 52.1, y: 82.5, connections: ['W-meet-5', 'W-meet-6', 'W-meet-end', 'W-meet-near-2'] },
      { id: 'W-meet-end', x: 31.2, y: 75.2, connections: ['W-meet-far-3', 'W-meet-near-3'] },
      { id: 'W-meet-1', x: 33.3, y: 64.4, connections: ['W-meet-far-2'] },
      { id: 'W-meet-2', x: 38.6, y: 60.8, connections: ['W-meet-far-2'] },
      { id: 'W-meet-3', x: 43.9, y: 57.1, connections: ['W-meet-far-2'] },
      { id: 'W-meet-4', x: 49.2, y: 53.5, connections: ['W-meet-far-1'] },
      { id: 'W-meet-5', x: 46.5, y: 74.1, connections: ['W-meet-near-3'] },
      { id: 'W-meet-6', x: 52.0, y: 70.3, connections: ['W-meet-near-3'] },
      { id: 'W-meet-7', x: 57.5, y: 66.5, connections: ['W-meet-near-2'] },
      { id: 'W-meet-8', x: 63.0, y: 62.6, connections: ['W-meet-in'] },
    ],
  },

  // Six racks along the left wall, one standing place in front of each (one MCP
  // server worker per rack), a network cabinet and a crash cart.
  'server-room': {
    id: 'server-room',
    name: 'Server Room',
    description: 'Racks, blinking lights and the MCP servers the sessions call.',
    background: {
      day: '/rooms/server-room-day.webp',
      night: '/rooms/server-room-night.webp',
    },
    backgroundDm: {
      day: '/rooms/server-room-day-dm.webp',
      night: '/rooms/server-room-night-dm.webp',
    },
    width: 800,
    height: 600,
    furniture: [
      { id: 'srv-rack-1', type: 'server-rack', sprite: 'server-rack-1', x: 41.4, y: 45.1, zIndex: 30 },
      { id: 'srv-rack-2', type: 'server-rack', sprite: 'server-rack-2', x: 36.6, y: 48.4, zIndex: 31 },
      { id: 'srv-rack-3', type: 'server-rack', sprite: 'server-rack-3', x: 31.8, y: 51.7, zIndex: 32 },
      { id: 'srv-rack-4', type: 'server-rack', sprite: 'server-rack-1', x: 26.9, y: 55.0, zIndex: 33 },
      { id: 'srv-rack-5', type: 'server-rack', sprite: 'server-rack-2', x: 22.1, y: 58.3, zIndex: 34 },
      { id: 'srv-rack-6', type: 'server-rack', sprite: 'server-rack-3', x: 17.3, y: 61.6, zIndex: 35 },
      { id: 'srv-cabinet', type: 'network-cabinet', sprite: 'network-cabinet', x: 12.2, y: 65.5, zIndex: 40 },
      { id: 'srv-cart', type: 'crash-cart', sprite: 'crash-cart', x: 79.8, y: 66.2, zIndex: 45 },

      // Core Ops: two benches of five standing desks on the free floor in front
      // of the racks, one behind each biz-s* spot. The worker faces away from
      // us, so the rear sprite (we see the monitor backs). A desk's zIndex is
      // its spot's minus 2: the worker at a desk draws over its own desk, and
      // the desk one step nearer draws over the worker in front of it.
      { id: 'biz-desk-1', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 31.0, y: 68.0, zIndex: 62 },
      { id: 'biz-desk-2', type: 'desk-standing', sprite: 'desk-standing-right-rear', x: 35.3, y: 70.6, zIndex: 66 },
      { id: 'biz-desk-3', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 39.6, y: 73.2, zIndex: 70 },
      { id: 'biz-desk-4', type: 'desk-standing', sprite: 'desk-standing-right-rear', x: 43.9, y: 75.8, zIndex: 74 },
      { id: 'biz-desk-5', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 48.2, y: 78.4, zIndex: 78 },
      { id: 'biz-desk-6', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 53.0, y: 68.0, zIndex: 62 },
      { id: 'biz-desk-7', type: 'desk-standing', sprite: 'desk-standing-right-rear', x: 57.3, y: 70.6, zIndex: 66 },
      { id: 'biz-desk-8', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 61.6, y: 73.2, zIndex: 70 },
      { id: 'biz-desk-9', type: 'desk-standing', sprite: 'desk-standing-right-rear', x: 65.9, y: 75.8, zIndex: 74 },
      { id: 'biz-desk-10', type: 'desk-standing', sprite: 'desk-standing-left-rear', x: 70.2, y: 78.4, zIndex: 78 },
    ],
    connections: [
      { toRoom: 'corridor', position: { x: 68.5, y: 53 }, label: 'Corridor', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 64.6, y: 24, w: 9.4, h: 29.6 } },
    ],
    agentSpots: [
      { id: 'srv-1', type: 'standing', x: 49.8, y: 47.6, facing: 'up', spriteFacing: 'rear-left', zIndex: 50 },
      { id: 'srv-2', type: 'standing', x: 45.0, y: 50.9, facing: 'up', spriteFacing: 'rear-left', zIndex: 51 },
      { id: 'srv-3', type: 'standing', x: 40.1, y: 54.3, facing: 'up', spriteFacing: 'rear-left', zIndex: 52 },
      { id: 'srv-4', type: 'standing', x: 35.3, y: 57.7, facing: 'up', spriteFacing: 'rear-left', zIndex: 53 },
      { id: 'srv-5', type: 'standing', x: 30.4, y: 61.0, facing: 'up', spriteFacing: 'rear-left', zIndex: 54 },
      { id: 'srv-6', type: 'standing', x: 25.6, y: 64.4, facing: 'up', spriteFacing: 'rear-left', zIndex: 55 },

      // Face of each desk above it; the two benches run along the floor in front of the racks
      { id: 'biz-s1', type: 'desk', x: 31.0, y: 68.0, facing: 'up', spriteFacing: 'rear-left', zIndex: 64 },
      { id: 'biz-s2', type: 'desk', x: 35.3, y: 70.6, facing: 'up', spriteFacing: 'rear-left', zIndex: 68 },
      { id: 'biz-s3', type: 'desk', x: 39.6, y: 73.2, facing: 'up', spriteFacing: 'rear-left', zIndex: 72 },
      { id: 'biz-s4', type: 'desk', x: 43.9, y: 75.8, facing: 'up', spriteFacing: 'rear-left', zIndex: 76 },
      { id: 'biz-s5', type: 'desk', x: 48.2, y: 78.4, facing: 'up', spriteFacing: 'rear-left', zIndex: 80 },
      { id: 'biz-s6', type: 'desk', x: 53.0, y: 68.0, facing: 'up', spriteFacing: 'rear-left', zIndex: 64 },
      { id: 'biz-s7', type: 'desk', x: 57.3, y: 70.6, facing: 'up', spriteFacing: 'rear-left', zIndex: 68 },
      { id: 'biz-s8', type: 'desk', x: 61.6, y: 73.2, facing: 'up', spriteFacing: 'rear-left', zIndex: 72 },
      { id: 'biz-s9', type: 'desk', x: 65.9, y: 75.8, facing: 'up', spriteFacing: 'rear-left', zIndex: 76 },
      { id: 'biz-s10', type: 'desk', x: 70.2, y: 78.4, facing: 'up', spriteFacing: 'rear-left', zIndex: 80 },
    ],
    entryPoint: { x: 68.5, y: 53 },
    walkableArea: [{ x: 43.8, y: 38.8 }, { x: 93.0, y: 65.6 }, { x: 54.5, y: 94.0 }, { x: 6.0, y: 64.6 }],
    waypoints: [
      { id: 'W-srv-door', x: 68.5, y: 53.0, connections: ['W-srv-in'] },
      { id: 'W-srv-in', x: 63.9, y: 55.3, connections: ['W-srv-aisle-1', 'W-srv-door', 'W-srv-biz'] },
      { id: 'W-srv-aisle-1', x: 56.6, y: 51.3, connections: ['W-srv-1', 'W-srv-aisle-2', 'W-srv-in'] },
      { id: 'W-srv-aisle-2', x: 46.9, y: 58.1, connections: ['W-srv-2', 'W-srv-3', 'W-srv-aisle-1', 'W-srv-aisle-3'] },
      { id: 'W-srv-aisle-3', x: 37.2, y: 65.0, connections: ['W-srv-4', 'W-srv-5', 'W-srv-aisle-2', 'W-srv-aisle-4'] },
      { id: 'W-srv-aisle-4', x: 27.4, y: 71.8, connections: ['W-srv-6', 'W-srv-aisle-3'] },
      { id: 'W-srv-1', x: 49.8, y: 47.6, connections: ['W-srv-aisle-1'] },
      { id: 'W-srv-2', x: 45.0, y: 50.9, connections: ['W-srv-aisle-2'] },
      { id: 'W-srv-3', x: 40.1, y: 54.3, connections: ['W-srv-aisle-2'] },
      { id: 'W-srv-4', x: 35.3, y: 57.7, connections: ['W-srv-aisle-3'] },
      { id: 'W-srv-5', x: 30.4, y: 61.0, connections: ['W-srv-aisle-3'] },
      { id: 'W-srv-6', x: 25.6, y: 64.4, connections: ['W-srv-aisle-4'] },

      // Core Ops: their own row of desks, reached from the door side of the room
      { id: 'W-srv-biz', x: 64.0, y: 64.0, connections: ['W-srv-in', 'W-biz-s1', 'W-biz-s2', 'W-biz-s3', 'W-biz-s4', 'W-biz-s5', 'W-biz-s6', 'W-biz-s7', 'W-biz-s8', 'W-biz-s9', 'W-biz-s10'] },
      { id: 'W-biz-s1', x: 31.0, y: 68.0, connections: ['W-srv-biz'] },
      { id: 'W-biz-s2', x: 35.3, y: 70.6, connections: ['W-srv-biz'] },
      { id: 'W-biz-s3', x: 39.6, y: 73.2, connections: ['W-srv-biz'] },
      { id: 'W-biz-s4', x: 43.9, y: 75.8, connections: ['W-srv-biz'] },
      { id: 'W-biz-s5', x: 48.2, y: 78.4, connections: ['W-srv-biz'] },
      { id: 'W-biz-s6', x: 53.0, y: 68.0, connections: ['W-srv-biz'] },
      { id: 'W-biz-s7', x: 57.3, y: 70.6, connections: ['W-srv-biz'] },
      { id: 'W-biz-s8', x: 61.6, y: 73.2, connections: ['W-srv-biz'] },
      { id: 'W-biz-s9', x: 65.9, y: 75.8, connections: ['W-srv-biz'] },
      { id: 'W-biz-s10', x: 70.2, y: 78.4, connections: ['W-srv-biz'] },
    ],
  },

  // Right wall: vending machine, fridge, water cooler, the door, then the counter
  // with the coffee machine. Two cafe tables of four in the middle.
  'lunch-room': {
    id: 'lunch-room',
    name: 'Lunch Room',
    description: 'Coffee, water and somewhere to sit when there is nothing to do.',
    background: {
      day: '/rooms/lunch-room-day.webp',
      night: '/rooms/lunch-room-night.webp',
    },
    backgroundDm: {
      day: '/rooms/lunch-room-day-dm.webp',
      night: '/rooms/lunch-room-night-dm.webp',
    },
    width: 800,
    height: 600,
    furniture: [
      { id: 'lunch-vending', type: 'vending-machine', sprite: 'vending-machine', x: 46.7, y: 42.1, zIndex: 30 },
      { id: 'lunch-fridge', type: 'fridge', sprite: 'fridge', x: 53.0, y: 45.2, zIndex: 31 },
      { id: 'lunch-water', type: 'water-cooler', sprite: 'water-cooler', x: 58.7, y: 47.8, zIndex: 32, label: 'Water Cooler' },
      { id: 'lunch-counter', type: 'kitchen-counter', sprite: 'kitchen-counter', x: 82.1, y: 62.0, zIndex: 33 },
      { id: 'lunch-coffee-machine', type: 'coffee-machine', sprite: 'coffee-off', x: 81.5, y: 54.5, zIndex: 34, label: 'Coffee Machine' },
      { id: 'lunch-table-1', type: 'cafe-table', sprite: 'cafe-table', x: 39.0, y: 66.8, zIndex: 60 },
      { id: 'lunch-chair-1', type: 'cafe-chair', sprite: 'cafe-chair-front-right', x: 33.3, y: 62.0, zIndex: 55 },
      { id: 'lunch-chair-2', type: 'cafe-chair', sprite: 'cafe-chair-front-left', x: 43.5, y: 62.1, zIndex: 55 },
      { id: 'lunch-chair-3', type: 'cafe-chair', sprite: 'cafe-chair-rear-left', x: 44.6, y: 68.7, zIndex: 66 },
      { id: 'lunch-chair-4', type: 'cafe-chair', sprite: 'cafe-chair-rear-right', x: 34.5, y: 68.6, zIndex: 66 },
      { id: 'lunch-table-2', type: 'cafe-table', sprite: 'cafe-table', x: 61.3, y: 73.5, zIndex: 70 },
      { id: 'lunch-chair-5', type: 'cafe-chair', sprite: 'cafe-chair-front-right', x: 55.7, y: 68.8, zIndex: 65 },
      { id: 'lunch-chair-6', type: 'cafe-chair', sprite: 'cafe-chair-front-left', x: 65.9, y: 68.7, zIndex: 65 },
      { id: 'lunch-chair-7', type: 'cafe-chair', sprite: 'cafe-chair-rear-left', x: 67.0, y: 75.4, zIndex: 76 },
      { id: 'lunch-chair-8', type: 'cafe-chair', sprite: 'cafe-chair-rear-right', x: 56.8, y: 75.4, zIndex: 76 },
    ],
    connections: [
      { toRoom: 'corridor', position: { x: 68.3, y: 52.3 }, label: 'Corridor', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 64.8, y: 21.5, w: 8.8, h: 30.1 } },
    ],
    agentSpots: [
      { id: 'lunch-water', type: 'water', x: 54.2, y: 50.1, facing: 'up', spriteFacing: 'rear-right', zIndex: 45 },
      { id: 'lunch-coffee', type: 'coffee', x: 78.1, y: 63.5, facing: 'up', spriteFacing: 'rear-right', zIndex: 45 },
      { id: 'lunch-1', type: 'lounge', x: 34.5, y: 62.3, facing: 'down', spriteFacing: 'front-right', zIndex: 57 },
      { id: 'lunch-2', type: 'lounge', x: 42.6, y: 62.4, facing: 'down', spriteFacing: 'front-left', zIndex: 57 },
      { id: 'lunch-3', type: 'lounge', x: 43.5, y: 67.7, facing: 'up', spriteFacing: 'rear-left', zIndex: 64 },
      { id: 'lunch-4', type: 'lounge', x: 35.4, y: 67.6, facing: 'up', spriteFacing: 'rear-right', zIndex: 64 },
      { id: 'lunch-5', type: 'lounge', x: 56.8, y: 69.1, facing: 'down', spriteFacing: 'front-right', zIndex: 67 },
      { id: 'lunch-6', type: 'lounge', x: 65.0, y: 69.0, facing: 'down', spriteFacing: 'front-left', zIndex: 67 },
      { id: 'lunch-7', type: 'lounge', x: 65.9, y: 74.3, facing: 'up', spriteFacing: 'rear-left', zIndex: 74 },
      { id: 'lunch-8', type: 'lounge', x: 57.7, y: 74.4, facing: 'up', spriteFacing: 'rear-right', zIndex: 74 },
    ],
    entryPoint: { x: 68.3, y: 52.3 },
    walkableArea: [{ x: 43.8, y: 37.2 }, { x: 92.7, y: 64.1 }, { x: 53.6, y: 93.1 }, { x: 5.9, y: 63.6 }],
    waypoints: [
      { id: 'W-lunch-door', x: 68.3, y: 52.3, connections: ['W-lunch-in'] },
      { id: 'W-lunch-in', x: 65.5, y: 55.9, connections: ['W-lunch-cooler', 'W-lunch-counter', 'W-lunch-door', 'W-lunch-mid'] },
      { id: 'W-lunch-counter', x: 76.8, y: 64.4, connections: ['W-lunch-coffee', 'W-lunch-east', 'W-lunch-in'] },
      { id: 'W-lunch-cooler', x: 53.0, y: 51.0, connections: ['W-lunch-in', 'W-lunch-water'] },
      { id: 'W-lunch-mid', x: 59.2, y: 61.8, connections: ['W-lunch-5', 'W-lunch-east', 'W-lunch-in', 'W-lunch-west'] },
      { id: 'W-lunch-west', x: 32.1, y: 59.9, connections: ['W-lunch-1', 'W-lunch-2', 'W-lunch-4', 'W-lunch-mid', 'W-lunch-south'] },
      { id: 'W-lunch-south', x: 38.5, y: 75.5, connections: ['W-lunch-3', 'W-lunch-east', 'W-lunch-west'] },
      { id: 'W-lunch-east', x: 68.5, y: 75.9, connections: ['W-lunch-6', 'W-lunch-7', 'W-lunch-8', 'W-lunch-counter', 'W-lunch-mid', 'W-lunch-south'] },
      { id: 'W-lunch-water', x: 54.2, y: 50.1, connections: ['W-lunch-cooler'] },
      { id: 'W-lunch-coffee', x: 78.1, y: 63.5, connections: ['W-lunch-counter'] },
      { id: 'W-lunch-1', x: 34.5, y: 62.3, connections: ['W-lunch-west'] },
      { id: 'W-lunch-2', x: 42.6, y: 62.4, connections: ['W-lunch-west'] },
      { id: 'W-lunch-3', x: 43.5, y: 67.7, connections: ['W-lunch-south'] },
      { id: 'W-lunch-4', x: 35.4, y: 67.6, connections: ['W-lunch-west'] },
      { id: 'W-lunch-5', x: 56.8, y: 69.1, connections: ['W-lunch-mid'] },
      { id: 'W-lunch-6', x: 65.0, y: 69.0, connections: ['W-lunch-east'] },
      { id: 'W-lunch-7', x: 65.9, y: 74.3, connections: ['W-lunch-east'] },
      { id: 'W-lunch-8', x: 57.7, y: 74.4, connections: ['W-lunch-east'] },
    ],
  },

  // ── Floor 2 ───────────────────────────────────────────────────────────────
  // Four rooms the business team works in. No new art: each one points its
  // background at a room already drawn and reuses that room's measured floor,
  // door and entry point (docs/hermes-office/ROOMS.md). What is new here is
  // only the business desks, which carry their own `biz-*` ids so no dev spot
  // is ever taken.
  'business-suite': {
    id: 'business-suite',
    name: 'Business Suite',
    description: 'Orchestrator, Sales, Marketing and Ops — where the business team is coordinated',
    floor: 2,
    artReuse: 'meeting-room',
    background: {
      day: '/rooms/meeting-room-day.webp',
      night: '/rooms/meeting-room-night.webp',
    },
    width: 800,
    height: 600,
    furniture: [],
    connections: [
      { toRoom: 'corridor', position: { x: 68, y: 51.5 }, label: 'Corridor (lift)', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 64.8, y: 21.8, w: 8.4, h: 28.4 } },
    ],
    agentSpots: [
      { id: 'biz-b1', type: 'desk', x: 33.3, y: 64.4, facing: 'down', spriteFacing: 'front-right', zIndex: 40 },
      { id: 'biz-b2', type: 'desk', x: 38.6, y: 60.8, facing: 'down', spriteFacing: 'front-right', zIndex: 41 },
      { id: 'biz-b3', type: 'desk', x: 43.9, y: 57.1, facing: 'down', spriteFacing: 'front-right', zIndex: 42 },
      { id: 'biz-b4', type: 'desk', x: 49.2, y: 53.5, facing: 'down', spriteFacing: 'front-right', zIndex: 43 },
      { id: 'biz-b5', type: 'desk', x: 46.5, y: 74.1, facing: 'up', spriteFacing: 'rear-left', zIndex: 60 },
      { id: 'biz-b6', type: 'desk', x: 52.0, y: 70.3, facing: 'up', spriteFacing: 'rear-left', zIndex: 61 },
    ],
    entryPoint: { x: 68, y: 51.5 },
    walkableArea: [{ x: 43.8, y: 37.0 }, { x: 93.0, y: 63.9 }, { x: 53.7, y: 93.1 }, { x: 5.9, y: 63.4 }],
    waypoints: [
      { id: 'W-biz-door', x: 68.0, y: 51.5, connections: ['W-biz-hub'] },
      { id: 'W-biz-hub', x: 57.0, y: 63.0, connections: ['W-biz-door', 'W-biz-1', 'W-biz-2', 'W-biz-3', 'W-biz-4', 'W-biz-5', 'W-biz-6'] },
      { id: 'W-biz-1', x: 33.3, y: 64.4, connections: ['W-biz-hub'] },
      { id: 'W-biz-2', x: 38.6, y: 60.8, connections: ['W-biz-hub'] },
      { id: 'W-biz-3', x: 43.9, y: 57.1, connections: ['W-biz-hub'] },
      { id: 'W-biz-4', x: 49.2, y: 53.5, connections: ['W-biz-hub'] },
      { id: 'W-biz-5', x: 46.5, y: 74.1, connections: ['W-biz-hub'] },
      { id: 'W-biz-6', x: 52.0, y: 70.3, connections: ['W-biz-hub'] },
    ],
  },

  'creative-studio': {
    id: 'creative-studio',
    name: 'Creative Studio',
    description: 'Growth, product and the premium pipeline: analytics, design, pricing, publishing',
    floor: 2,
    artReuse: 'main-office',
    background: {
      day: '/rooms/office-day.png',
      night: '/rooms/office-night.png',
    },
    width: 800,
    height: 600,
    furniture: [],
    connections: [
      { toRoom: 'corridor', position: { x: 67.5, y: 48.9 }, label: 'Corridor (lift)', exitFacing: 'rear-right', entryFacing: 'front-right', door: { x: 64.8, y: 21.8, w: 7.7, h: 27.3 } },
    ],
    agentSpots: [
      { id: 'biz-c1', type: 'desk', x: 25.8, y: 71.0, facing: 'down', spriteFacing: 'rear-left', zIndex: 85 },
      { id: 'biz-c2', type: 'desk', x: 37.9, y: 68.2, facing: 'down', spriteFacing: 'rear-right', zIndex: 85 },
      { id: 'biz-c3', type: 'desk', x: 26.9, y: 59.2, facing: 'down', spriteFacing: 'front-left', zIndex: 40 },
      { id: 'biz-c4', type: 'desk', x: 38.5, y: 55.2, facing: 'down', spriteFacing: 'rear-left', zIndex: 58 },
      { id: 'biz-c5', type: 'desk', x: 48.9, y: 52.9, facing: 'down', spriteFacing: 'rear-right', zIndex: 70 },
      { id: 'biz-c6', type: 'desk', x: 38.8, y: 43.6, facing: 'down', spriteFacing: 'front-left', zIndex: 30 },
      { id: 'biz-c7', type: 'desk', x: 52.7, y: 78.8, facing: 'down', spriteFacing: 'rear-left', zIndex: 95 },
      { id: 'biz-c8', type: 'desk', x: 65.9, y: 75.8, facing: 'down', spriteFacing: 'rear-right', zIndex: 95 },
      { id: 'biz-c9', type: 'desk', x: 55.2, y: 66.8, facing: 'down', spriteFacing: 'front-left', zIndex: 55 },
      { id: 'biz-c10', type: 'desk', x: 68.7, y: 66.2, facing: 'down', spriteFacing: 'front-right', zIndex: 55 },
    ],
    entryPoint: { x: 67.5, y: 48.9 },
    walkableArea: [
      { x: 28.2, y: 46 }, { x: 33, y: 50.2 }, { x: 20.6, y: 60.9 }, { x: 21.8, y: 65.5 },
      { x: 32, y: 71.4 }, { x: 41.6, y: 62.7 }, { x: 40.8, y: 58.1 }, { x: 45.5, y: 56.3 },
      { x: 49.3, y: 54.5 }, { x: 51.3, y: 52.2 }, { x: 51.9, y: 49.3 }, { x: 51.5, y: 46.7 },
      { x: 57.9, y: 47.3 }, { x: 64.2, y: 47.4 }, { x: 70, y: 49.9 }, { x: 71.2, y: 55.4 },
      { x: 78.8, y: 60.7 }, { x: 86.7, y: 65.6 }, { x: 82.6, y: 72.8 }, { x: 71.5, y: 68.4 },
      { x: 59.5, y: 57.1 }, { x: 54.7, y: 61.9 }, { x: 51.4, y: 65.9 }, { x: 49.8, y: 70.1 },
      { x: 50, y: 75.3 }, { x: 54.3, y: 78.2 }, { x: 58.1, y: 80 }, { x: 62.5, y: 78.9 },
      { x: 64.9, y: 76 }, { x: 68.4, y: 73.3 }, { x: 70.4, y: 71.1 }, { x: 71.7, y: 69.3 },
      { x: 82.7, y: 73.4 }, { x: 54.3, y: 93.6 }, { x: 37.6, y: 84 }, { x: 23.5, y: 75.6 },
      { x: 12.6, y: 68.8 }, { x: 3.9, y: 62.9 }, { x: 33.7, y: 42.4 }, { x: 35.5, y: 48.6 },
    ],
    waypoints: [
      { id: 'W-creative-door', x: 67.5, y: 48.9, connections: ['W-creative-hub'] },
      { id: 'W-creative-hub', x: 55.5, y: 60.0, connections: ['W-creative-door', 'W-creative-1', 'W-creative-2', 'W-creative-3', 'W-creative-4', 'W-creative-5', 'W-creative-6', 'W-creative-7', 'W-creative-8', 'W-creative-9', 'W-creative-10'] },
      { id: 'W-creative-1', x: 25.8, y: 71.0, connections: ['W-creative-hub'] },
      { id: 'W-creative-2', x: 37.9, y: 68.2, connections: ['W-creative-hub'] },
      { id: 'W-creative-3', x: 26.9, y: 59.2, connections: ['W-creative-hub'] },
      { id: 'W-creative-4', x: 38.5, y: 55.2, connections: ['W-creative-hub'] },
      { id: 'W-creative-5', x: 48.9, y: 52.9, connections: ['W-creative-hub'] },
      { id: 'W-creative-6', x: 38.8, y: 43.6, connections: ['W-creative-hub'] },
      { id: 'W-creative-7', x: 52.7, y: 78.8, connections: ['W-creative-hub'] },
      { id: 'W-creative-8', x: 65.9, y: 75.8, connections: ['W-creative-hub'] },
      { id: 'W-creative-9', x: 55.2, y: 66.8, connections: ['W-creative-hub'] },
      { id: 'W-creative-10', x: 68.7, y: 66.2, connections: ['W-creative-hub'] },
    ],
  },

  'finance-legal': {
    id: 'finance-legal',
    name: 'Finance & Legal',
    description: 'Revenue, payments, DMCA and SecOps — the room that keeps the books and the rules',
    floor: 2,
    artReuse: 'server-room',
    background: {
      day: '/rooms/server-room-day.webp',
      night: '/rooms/server-room-night.webp',
    },
    width: 800,
    height: 600,
    furniture: [],
    connections: [
      { toRoom: 'corridor', position: { x: 68.5, y: 53 }, label: 'Corridor (lift)', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 64.6, y: 24, w: 9.4, h: 29.6 } },
    ],
    agentSpots: [
      { id: 'biz-f1', type: 'desk', x: 30.4, y: 61.0, facing: 'up', spriteFacing: 'rear-left', zIndex: 54 },
      { id: 'biz-f2', type: 'desk', x: 35.3, y: 57.7, facing: 'up', spriteFacing: 'rear-left', zIndex: 53 },
      { id: 'biz-f3', type: 'desk', x: 40.1, y: 54.3, facing: 'up', spriteFacing: 'rear-left', zIndex: 52 },
      { id: 'biz-f4', type: 'desk', x: 45.0, y: 50.9, facing: 'up', spriteFacing: 'rear-left', zIndex: 51 },
    ],
    entryPoint: { x: 68.5, y: 53 },
    walkableArea: [{ x: 43.8, y: 38.8 }, { x: 93.0, y: 65.6 }, { x: 54.5, y: 94.0 }, { x: 6.0, y: 64.6 }],
    waypoints: [
      { id: 'W-fin-door', x: 68.5, y: 53.0, connections: ['W-fin-hub'] },
      { id: 'W-fin-hub', x: 55.0, y: 60.0, connections: ['W-fin-door', 'W-fin-1', 'W-fin-2', 'W-fin-3', 'W-fin-4'] },
      { id: 'W-fin-1', x: 30.4, y: 61.0, connections: ['W-fin-hub'] },
      { id: 'W-fin-2', x: 35.3, y: 57.7, connections: ['W-fin-hub'] },
      { id: 'W-fin-3', x: 40.1, y: 54.3, connections: ['W-fin-hub'] },
      { id: 'W-fin-4', x: 45.0, y: 50.9, connections: ['W-fin-hub'] },
    ],
  },

  'exec-floor': {
    id: 'exec-floor',
    name: 'Exec Floor',
    description: 'The boss’s room upstairs: final calls, approvals and a quiet desk',
    floor: 2,
    artReuse: 'meeting-room',
    background: {
      day: '/rooms/meeting-room-day.webp',
      night: '/rooms/meeting-room-night.webp',
    },
    width: 800,
    height: 600,
    furniture: [],
    connections: [
      { toRoom: 'corridor', position: { x: 68, y: 51.5 }, label: 'Corridor (lift)', exitFacing: 'rear-right', entryFacing: 'front-left', door: { x: 64.8, y: 21.8, w: 8.4, h: 28.4 } },
    ],
    agentSpots: [
      { id: 'exec-1', type: 'desk', x: 33.3, y: 64.4, facing: 'down', spriteFacing: 'front-right', zIndex: 40 },
      { id: 'exec-2', type: 'desk', x: 38.6, y: 60.8, facing: 'down', spriteFacing: 'front-right', zIndex: 41 },
    ],
    entryPoint: { x: 68, y: 51.5 },
    walkableArea: [{ x: 43.8, y: 37.0 }, { x: 93.0, y: 63.9 }, { x: 53.7, y: 93.1 }, { x: 5.9, y: 63.4 }],
    waypoints: [
      { id: 'W-exec-door', x: 68.0, y: 51.5, connections: ['W-exec-hub'] },
      { id: 'W-exec-hub', x: 55.0, y: 62.0, connections: ['W-exec-door', 'W-exec-1', 'W-exec-2'] },
      { id: 'W-exec-1', x: 33.3, y: 64.4, connections: ['W-exec-hub'] },
      { id: 'W-exec-2', x: 38.6, y: 60.8, connections: ['W-exec-hub'] },
    ],
  },
}

/** Every room, in the order the floor plan lists them */
export const ROOM_IDS = Object.keys(ROOMS) as RoomId[]

// ===== ROOM NAVIGATION =====

/**
 * The rooms to pass through from one room to another, both ends included
 * (breadth-first over the doors, so the shortest way).
 * @param from the room to start in
 * @param to the room to reach
 * @returns the route, `[from]` when the two are the same or no door leads there
 */
export function findRoomPath(from: RoomId, to: RoomId): RoomId[] {
  if (from === to) return [from]

  const visited = new Set<RoomId>()
  const queue: { room: RoomId; path: RoomId[] }[] = [{ room: from, path: [from] }]
  visited.add(from)

  while (queue.length > 0) {
    const { room, path } = queue.shift()!
    const connections = ROOMS[room].connections

    for (const conn of connections) {
      if (conn.toRoom === to) return [...path, to]
      if (!visited.has(conn.toRoom)) {
        visited.add(conn.toRoom)
        queue.push({ room: conn.toRoom, path: [...path, conn.toRoom] })
      }
    }
  }

  return [from] // no path found, stay put
}

/**
 * The rooms a room's doors lead to.
 * @param roomId the room to stand in
 * @returns the rooms next door
 */
export function getConnectedRooms(roomId: RoomId): RoomId[] {
  return ROOMS[roomId].connections.map(c => c.toRoom)
}

/**
 * Where in `roomId` the door to `toRoom` is.
 * @param roomId the room to stand in
 * @param toRoom the room behind the door
 * @returns the door's position, or null when no door of this room leads there
 */
export function doorTo(roomId: RoomId, toRoom: RoomId): { x: number; y: number } | null {
  const conn = ROOMS[roomId].connections.find(c => c.toRoom === toRoom)
  return conn ? { x: conn.position.x, y: conn.position.y } : null
}

/**
 * A free agent spot in a room, in the order the room lists them.
 * @param roomId the room to look in
 * @param occupiedSpotIds spots somebody already holds
 * @param type only spots of this kind (any kind when omitted)
 * @returns the first free spot, or null when the room is full
 */
export function getFreeSpot(
  roomId: RoomId,
  occupiedSpotIds: Set<string>,
  type?: AgentSpot['type'],
): AgentSpot | null {
  const room = ROOMS[roomId]
  const spots = type
    ? room.agentSpots.filter(s => s.type === type)
    : room.agentSpots

  for (const spot of spots) {
    if (!occupiedSpotIds.has(spot.id)) return spot
  }
  return null
}

/**
 * Look a spot up by id in any room. Spot ids are unique across the building
 * (tests/rooms.test.ts), so the id alone says which room it is in.
 * @param spotId the spot's id
 * @returns the spot and its room, or null for an unknown id
 */
export function findSpot(spotId: string | undefined): { room: RoomId; spot: AgentSpot } | null {
  if (!spotId) return null
  for (const id of ROOM_IDS) {
    const spot = ROOMS[id].agentSpots.find(s => s.id === spotId)
    if (spot) return { room: id, spot }
  }
  return null
}
