# ARCHITECTURE.md - Open WebUI System Architecture

Comprehensive system architecture guide for Open WebUI implementation patterns.

## System Overview

Open WebUI is a full-stack AI chat interface built with SvelteKit frontend and FastAPI backend, designed for multiple AI provider integration.

**Core Architecture**: 
- **Frontend**: SvelteKit + TypeScript + TailwindCSS (Static SPA deployment)
- **Backend**: FastAPI + Python (API-first design)
- **Database**: SQLAlchemy + Peewee (Multi-database support)
- **AI Integration**: Multi-model provider support (Ollama, OpenAI, Azure, etc.)
- **Real-time**: WebSocket + Server-Sent Events
- **Storage**: Redis (caching), File system (uploads), Vector databases (RAG)

## Frontend Architecture

### SvelteKit Patterns

**File-based Routing System**:
```
src/routes/
├── (app)/                      # Layout group for authenticated app
│   ├── +layout.svelte         # Main app layout with auth
│   ├── +page.svelte          # Dashboard/chat interface
│   └── [chatId]/             # Dynamic chat routes
├── auth/                      # Authentication pages
│   ├── +page.svelte          # Login page
│   └── signin/               # Sign-in flow
└── api/                      # API route handlers
```

**Load Functions Pattern**:
- Server-side data fetching in `+page.server.ts`
- Client-side hydration with `+page.ts`
- Data validation with form actions

**State Management Architecture**:
```typescript
// Svelte stores for global state
import { writable, derived } from 'svelte/store';

export const user = writable(null);
export const models = writable([]);
export const settings = writable({});
export const chats = derived([user], ([$user]) => {
    // Reactive state management
});
```

**Component Patterns**:
- Composition-based component architecture
- TypeScript interfaces for props
- Reactive statements for computed values
- Event forwarding for parent-child communication

### TypeScript Integration

**Interface Definitions**:
```typescript
// User types
interface User {
    id: string;
    email: string;
    name: string;
    role: 'admin' | 'user';
    permissions: UserPermissions;
}

// Chat types
interface ChatMessage {
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    timestamp: number;
    model?: string;
}

// API Response types
interface ApiResponse<T> {
    data: T;
    error?: string;
    status: 'success' | 'error';
}
```

**Module Resolution**:
- ES modules with `.ts` extensions
- Path aliases configured in `tsconfig.json`
- Type-safe imports across frontend/backend boundary

### TailwindCSS Component System

**Utility-First Patterns**:
```html
<!-- Responsive chat interface -->
<div class="flex h-screen bg-white dark:bg-gray-900">
    <aside class="hidden md:flex md:w-64 md:flex-col">
        <!-- Sidebar content -->
    </aside>
    <main class="flex-1 flex flex-col overflow-hidden">
        <!-- Chat area -->
    </main>
</div>
```

**Component Classes**:
```css
@layer components {
    .btn-primary {
        @apply px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 
               focus:ring-2 focus:ring-blue-500 focus:ring-offset-2;
    }
    
    .chat-message {
        @apply p-4 rounded-lg mb-4 max-w-3xl;
    }
    
    .chat-message--user {
        @apply bg-blue-50 dark:bg-blue-900/20 ml-auto;
    }
    
    .chat-message--assistant {
        @apply bg-gray-50 dark:bg-gray-800;
    }
}
```

**Dark Mode Implementation**:
- Class-based dark mode strategy
- System preference detection
- Persistent user preference storage

## Backend Architecture

### FastAPI Application Structure

**Dependency Injection Pattern**:
```python
# Dependency hierarchy
async def get_db() -> AsyncSession:
    """Database session dependency"""
    
async def get_current_user(token: str = Depends(get_token)) -> User:
    """Authentication dependency"""
    
async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    """Authorization dependency"""
```

**Middleware Stack**:
```python
# Application middleware configuration
app.add_middleware(CORSMiddleware)
app.add_middleware(GZipMiddleware)  
app.add_middleware(TrustedHostMiddleware)
app.add_middleware(HTTPSRedirectMiddleware)
```

**Router Organization**:
```python
# Modular router structure
from .routers import auth, chats, models, admin, users

app.include_router(auth.router, prefix="/api/v1/auths")
app.include_router(chats.router, prefix="/api/v1/chats")  
app.include_router(models.router, prefix="/api/v1/models")
```

### Database Architecture

**Multi-ORM Strategy**:
- **SQLAlchemy**: Main ORM for complex queries and relationships
- **Peewee**: Legacy support and lightweight operations
- **Database Support**: PostgreSQL, MySQL, SQLite

**Model Definitions**:
```python
class User(SQLAlchemyBase):
    __tablename__ = "user"
    
    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER)
    
    # Relationships
    chats = relationship("Chat", back_populates="user")
    
class Chat(SQLAlchemyBase):
    __tablename__ = "chat"
    
    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    user_id = Column(String, ForeignKey("user.id"))
    
    # JSON fields for flexible data
    chat = Column(JSON)  # Message history
    share_id = Column(String, unique=True, nullable=True)
```

### AI Integration Layer

**Provider Abstraction**:
```python
# Abstract base for AI providers
class AIProvider(ABC):
    @abstractmethod
    async def chat_completion(self, messages: List[Message]) -> ChatResponse:
        pass
    
    @abstractmethod
    async def stream_completion(self, messages: List[Message]) -> AsyncIterator[str]:
        pass

# Concrete implementations
class OllamaProvider(AIProvider):
    def __init__(self, base_url: str):
        self.client = httpx.AsyncClient(base_url=base_url)
        
class OpenAIProvider(AIProvider):
    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)
```

**Model Configuration**:
```python
# Dynamic model discovery
async def get_available_models() -> List[ModelInfo]:
    """Discover models from all configured providers"""
    models = []
    for provider in enabled_providers:
        provider_models = await provider.list_models()
        models.extend(provider_models)
    return models
```

## Real-time Communication

### WebSocket Architecture

**Connection Management**:
```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
    
    async def broadcast_to_user(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            await websocket.send_json(message)
```

**Message Streaming**:
```javascript
// Frontend WebSocket handling
class ChatSocket {
    connect() {
        this.ws = new WebSocket(`${WEBSOCKET_URL}/ws/${userId}`);
        this.ws.onmessage = this.handleMessage.bind(this);
    }
    
    handleMessage(event) {
        const data = JSON.parse(event.data);
        if (data.type === 'chat_chunk') {
            this.appendToMessage(data.chunk);
        }
    }
}
```

## Security Architecture

### Authentication Flow

**JWT Token Strategy**:
```python
# Token creation and validation
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user_from_token(token: str = Depends(oauth2_scheme)) -> User:
    """Dependency for protected routes"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = await get_user_by_id(user_id)
    if user is None:
        raise credentials_exception
    return user
```

### Authorization Patterns

**Role-Based Access Control (RBAC)**:
```python
class UserRole(Enum):
    ADMIN = "admin" 
    USER = "user"
    PENDING = "pending"

def require_admin(user: User = Depends(get_current_user)):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# Usage in routes
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_admin)
):
    pass
```

**Permission System**:
```python
@dataclass
class UserPermissions:
    chat: ChatPermissions
    workspace: WorkspacePermissions
    
@dataclass  
class ChatPermissions:
    delete: bool = True
    edit: bool = True
    temporary: bool = True
    temporary_enforced: bool = False
```

## Data Flow Patterns

### API Request Flow
1. **Client Request** → SvelteKit fetch/form action
2. **FastAPI Router** → Route handler with dependencies
3. **Authentication** → JWT validation and user resolution
4. **Authorization** → Permission checks
5. **Business Logic** → Service layer processing
6. **Database** → SQLAlchemy/Peewee operations
7. **Response** → JSON serialization back to client

### Chat Message Flow
1. **User Input** → SvelteKit chat component
2. **WebSocket/HTTP** → Message sent to FastAPI
3. **AI Provider** → Model inference request
4. **Streaming Response** → Chunked response via WebSocket
5. **Database Persistence** → Chat history storage
6. **UI Update** → Real-time message display

## Configuration Management

### Environment-based Configuration
```python
class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./webui.db"
    
    # Authentication  
    JWT_SECRET_KEY: str = secrets.token_urlsafe(32)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 1440
    
    # AI Providers
    OLLAMA_BASE_URL: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    
    # Features
    ENABLE_SIGNUP: bool = True
    ENABLE_LOGIN_FORM: bool = True
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Frontend Configuration
```typescript
// Environment-specific settings
export const config = {
    api: {
        baseUrl: import.meta.env.VITE_API_BASE_URL || '/api/v1',
        websocketUrl: import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8080'
    },
    features: {
        enableSignup: import.meta.env.VITE_ENABLE_SIGNUP === 'true',
        enableOAuth: import.meta.env.VITE_ENABLE_OAUTH === 'true'
    }
};
```

## Deployment Architecture

### Static SPA Deployment
- **Build Process**: SvelteKit static adapter generates SPA
- **Asset Optimization**: Vite bundling with tree shaking
- **Routing**: Client-side routing with fallback to index.html
- **API Proxy**: Configure reverse proxy for `/api/*` routes

### Backend Deployment Options
- **Development**: Uvicorn ASGI server
- **Production**: Gunicorn + Uvicorn workers
- **Container**: Docker with multi-stage builds
- **Database**: Separate database server (PostgreSQL recommended)

This architecture provides a scalable, maintainable foundation for AI chat interface development with clear separation of concerns and modern web development practices.