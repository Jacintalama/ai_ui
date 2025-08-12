# API_PATTERNS.md - Open WebUI API Design Patterns

API design patterns and conventions for Open WebUI backend and frontend integration.

## API Design Philosophy

**Core Principles**:
- **RESTful Design**: Follow REST conventions with clear resource naming
- **Type Safety**: Full TypeScript integration between frontend and backend
- **Consistent Error Handling**: Standardized error responses and status codes
- **Security First**: Authentication and authorization on all protected endpoints
- **Performance Optimized**: Efficient queries, caching, and pagination
- **Extensible**: Designed for future feature additions

## FastAPI Backend Patterns

### Router Organization

**Modular Router Structure**:
```python
# main.py - Application setup
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .routers import auth, users, chats, models, admin, tools, knowledge
from .middleware import AuthMiddleware, ErrorHandlingMiddleware

app = FastAPI(
    title="Open WebUI API",
    description="AI Chat Interface API",
    version="0.4.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Middleware stack
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, 
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
app.add_middleware(AuthMiddleware)
app.add_middleware(ErrorHandlingMiddleware)

# API route registration
app.include_router(auth.router, prefix="/api/v1/auths", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(chats.router, prefix="/api/v1/chats", tags=["Chats"])
app.include_router(models.router, prefix="/api/v1/models", tags=["Models"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(tools.router, prefix="/api/v1/tools", tags=["Tools"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["Knowledge"])
```

### Response Standards

**Consistent Response Format**:
```python
# schemas/responses.py
from pydantic import BaseModel, Field
from typing import TypeVar, Generic, Optional, Any, List
from enum import Enum

T = TypeVar('T')

class ResponseStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"

class APIResponse(BaseModel, Generic[T]):
    """Standard API response format"""
    status: ResponseStatus = ResponseStatus.SUCCESS
    data: Optional[T] = None
    message: Optional[str] = None
    error: Optional[str] = None
    
class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response format"""
    items: List[T]
    total: int
    page: int = Field(ge=1)
    size: int = Field(ge=1, le=100)
    pages: int
    has_next: bool
    has_prev: bool

class ListResponse(APIResponse[List[T]], Generic[T]):
    """Response for list endpoints"""
    pass

class DetailResponse(APIResponse[T], Generic[T]):
    """Response for detail endpoints"""
    pass

# Usage in routers
@router.get("/items", response_model=APIResponse[List[ItemResponse]])
async def get_items():
    items = await item_service.get_all()
    return APIResponse(data=items)

@router.get("/items/{item_id}", response_model=APIResponse[ItemResponse])
async def get_item(item_id: str):
    item = await item_service.get_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return APIResponse(data=item)
```

**Error Response Standards**:
```python
# exceptions.py
from fastapi import HTTPException
from typing import Dict, Any, Optional

class APIError(HTTPException):
    def __init__(
        self,
        status_code: int,
        detail: str,
        error_code: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code
        self.extra = extra or {}

# Common error factories
class ErrorFactory:
    @staticmethod
    def not_found(resource: str, identifier: str = None) -> APIError:
        detail = f"{resource} not found"
        if identifier:
            detail += f" (ID: {identifier})"
        return APIError(
            status_code=404,
            detail=detail,
            error_code="RESOURCE_NOT_FOUND"
        )
    
    @staticmethod
    def unauthorized(detail: str = "Authentication required") -> APIError:
        return APIError(
            status_code=401,
            detail=detail,
            error_code="UNAUTHORIZED"
        )
    
    @staticmethod
    def forbidden(detail: str = "Insufficient permissions") -> APIError:
        return APIError(
            status_code=403,
            detail=detail,
            error_code="FORBIDDEN"
        )
    
    @staticmethod
    def validation_error(field: str, message: str) -> APIError:
        return APIError(
            status_code=422,
            detail=f"Validation error: {message}",
            error_code="VALIDATION_ERROR",
            extra={"field": field}
        )
    
    @staticmethod
    def conflict(detail: str) -> APIError:
        return APIError(
            status_code=409,
            detail=detail,
            error_code="CONFLICT"
        )

# Global exception handler
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "error": exc.detail,
            "error_code": exc.error_code,
            "extra": exc.extra
        }
    )
```

### Authentication & Authorization Patterns

**JWT-Based Authentication**:
```python
# auth/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
import jwt
from datetime import datetime, timedelta

from ..database import get_db
from ..models import User
from ..config import settings

security = HTTPBearer(auto_error=False)

class AuthenticationError(HTTPException):
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"}
        )

class PermissionError(HTTPException):
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current user without raising exception if not authenticated"""
    if not credentials:
        return None
    
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        user_id: str = payload.get("sub")
        if not user_id:
            return None
        
        # Get user from database
        user = await get_user_by_id(db, user_id)
        return user
        
    except jwt.InvalidTokenError:
        return None

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current user with authentication required"""
    if not credentials:
        raise AuthenticationError("Missing authentication token")
    
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        user_id: str = payload.get("sub")
        exp: int = payload.get("exp")
        
        if not user_id:
            raise AuthenticationError("Invalid token: missing user ID")
        
        if exp and datetime.utcnow().timestamp() > exp:
            raise AuthenticationError("Token has expired")
        
        # Get user from database
        user = await get_user_by_id(db, user_id)
        if not user:
            raise AuthenticationError("User not found")
        
        if not user.is_active:
            raise AuthenticationError("User account is inactive")
        
        return user
        
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid authentication token")

# Role-based authorization
def require_role(required_roles: List[str]):
    """Dependency factory for role-based authorization"""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in required_roles:
            raise PermissionError(
                f"Access denied. Required role: {' or '.join(required_roles)}"
            )
        return current_user
    
    return role_checker

# Permission-based authorization
def require_permission(permission: str):
    """Dependency factory for permission-based authorization"""
    def permission_checker(current_user: User = Depends(get_current_user)) -> User:
        if not user_has_permission(current_user, permission):
            raise PermissionError(f"Permission required: {permission}")
        return current_user
    
    return permission_checker

# Convenience dependencies
get_admin_user = require_role(["admin"])
get_moderator_or_admin = require_role(["moderator", "admin"])

# Usage in routes
@router.get("/admin/users")
async def get_all_users(admin_user: User = Depends(get_admin_user)):
    """Admin-only endpoint"""
    pass

@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    current_user: User = Depends(require_permission("chats.delete"))
):
    """Permission-based endpoint"""
    pass
```

### Database Patterns

**Service Layer with Repository Pattern**:
```python
# services/base_service.py
from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from typing import TypeVar, Generic, Optional, List, Dict, Any
from uuid import uuid4

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType")
UpdateSchemaType = TypeVar("UpdateSchemaType")

class BaseService(ABC, Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """Base service class with common CRUD operations"""
    
    def __init__(self, db: AsyncSession, model: type[ModelType]):
        self.db = db
        self.model = model
    
    async def get_by_id(self, id: str) -> Optional[ModelType]:
        """Get record by ID"""
        stmt = select(self.model).where(self.model.id == id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_all(
        self, 
        skip: int = 0, 
        limit: int = 100,
        **filters
    ) -> List[ModelType]:
        """Get all records with optional filtering"""
        stmt = select(self.model)
        
        # Apply filters
        for key, value in filters.items():
            if hasattr(self.model, key) and value is not None:
                stmt = stmt.where(getattr(self.model, key) == value)
        
        stmt = stmt.offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_count(self, **filters) -> int:
        """Get total count with optional filtering"""
        stmt = select(func.count(self.model.id))
        
        # Apply filters
        for key, value in filters.items():
            if hasattr(self.model, key) and value is not None:
                stmt = stmt.where(getattr(self.model, key) == value)
        
        result = await self.db.execute(stmt)
        return result.scalar()
    
    async def create(self, obj_in: CreateSchemaType, **kwargs) -> ModelType:
        """Create new record"""
        obj_data = obj_in.dict() if hasattr(obj_in, 'dict') else obj_in
        obj_data.update(kwargs)
        
        # Generate ID if not provided
        if 'id' not in obj_data:
            obj_data['id'] = str(uuid4())
        
        db_obj = self.model(**obj_data)
        self.db.add(db_obj)
        await self.db.commit()
        await self.db.refresh(db_obj)
        return db_obj
    
    async def update(
        self, 
        id: str, 
        obj_in: UpdateSchemaType,
        **kwargs
    ) -> Optional[ModelType]:
        """Update existing record"""
        # Check if record exists
        existing = await self.get_by_id(id)
        if not existing:
            return None
        
        update_data = obj_in.dict(exclude_unset=True) if hasattr(obj_in, 'dict') else obj_in
        update_data.update(kwargs)
        
        if update_data:
            stmt = (
                update(self.model)
                .where(self.model.id == id)
                .values(**update_data)
            )
            await self.db.execute(stmt)
            await self.db.commit()
        
        return await self.get_by_id(id)
    
    async def delete(self, id: str) -> bool:
        """Delete record by ID"""
        stmt = delete(self.model).where(self.model.id == id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0
    
    async def exists(self, id: str) -> bool:
        """Check if record exists"""
        stmt = select(func.count(self.model.id)).where(self.model.id == id)
        result = await self.db.execute(stmt)
        return result.scalar() > 0

# Specific service implementation
class ChatService(BaseService[Chat, ChatCreate, ChatUpdate]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, Chat)
    
    async def get_user_chats(
        self, 
        user_id: str, 
        skip: int = 0, 
        limit: int = 50
    ) -> List[Chat]:
        """Get chats for a specific user"""
        return await self.get_all(skip=skip, limit=limit, user_id=user_id)
    
    async def get_shared_chats(self) -> List[Chat]:
        """Get publicly shared chats"""
        stmt = (
            select(Chat)
            .where(Chat.share_id.isnot(None))
            .order_by(Chat.updated_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def share_chat(self, chat_id: str, share_id: str) -> Optional[Chat]:
        """Make a chat publicly shareable"""
        return await self.update(chat_id, {"share_id": share_id})
    
    async def unshare_chat(self, chat_id: str) -> Optional[Chat]:
        """Remove public sharing from a chat"""
        return await self.update(chat_id, {"share_id": None})
```

### Pagination Patterns

**Standardized Pagination**:
```python
# utils/pagination.py
from typing import TypeVar, Generic, List
from pydantic import BaseModel, Field
from math import ceil

T = TypeVar('T')

class PaginationParams(BaseModel):
    page: int = Field(1, ge=1, description="Page number")
    size: int = Field(20, ge=1, le=100, description="Items per page")
    
    @property
    def skip(self) -> int:
        return (self.page - 1) * self.size
    
    @property
    def limit(self) -> int:
        return self.size

class PaginatedResult(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    size: int
    pages: int
    has_next: bool
    has_prev: bool
    
    @classmethod
    def create(
        cls, 
        items: List[T], 
        total: int, 
        page: int, 
        size: int
    ) -> 'PaginatedResult[T]':
        pages = ceil(total / size) if total > 0 else 1
        
        return cls(
            items=items,
            total=total,
            page=page,
            size=size,
            pages=pages,
            has_next=page < pages,
            has_prev=page > 1
        )

# Usage in services
async def get_paginated_chats(
    self,
    user_id: str,
    pagination: PaginationParams
) -> PaginatedResult[Chat]:
    """Get paginated chats for user"""
    
    # Get items
    items = await self.get_all(
        skip=pagination.skip,
        limit=pagination.limit,
        user_id=user_id
    )
    
    # Get total count
    total = await self.get_count(user_id=user_id)
    
    return PaginatedResult.create(
        items=items,
        total=total,
        page=pagination.page,
        size=pagination.size
    )

# Usage in routers
@router.get("/chats", response_model=APIResponse[PaginatedResult[ChatResponse]])
async def get_user_chats(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    chat_service = ChatService(db)
    result = await chat_service.get_paginated_chats(current_user.id, pagination)
    return APIResponse(data=result)
```

## Frontend API Integration Patterns

### Type-Safe API Client

**Base API Client**:
```typescript
// lib/apis/base.ts
import { browser } from '$app/environment';
import { goto } from '$app/navigation';

export interface APIResponse<T = any> {
    status: 'success' | 'error' | 'partial';
    data?: T;
    message?: string;
    error?: string;
    error_code?: string;
    extra?: Record<string, any>;
}

export interface PaginatedResponse<T> {
    items: T[];
    total: number;
    page: number;
    size: number;
    pages: number;
    has_next: boolean;
    has_prev: boolean;
}

export class APIError extends Error {
    constructor(
        public status: number,
        public error_code?: string,
        message?: string,
        public extra?: Record<string, any>
    ) {
        super(message || `API Error ${status}`);
        this.name = 'APIError';
    }
}

export class APIClient {
    private baseURL: string;
    private defaultHeaders: HeadersInit;
    
    constructor(baseURL: string = '/api/v1') {
        this.baseURL = baseURL;
        this.defaultHeaders = {
            'Content-Type': 'application/json'
        };
    }
    
    private getAuthToken(): string | null {
        if (!browser) return null;
        return localStorage.getItem('token');
    }
    
    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<APIResponse<T>> {
        const token = this.getAuthToken();
        
        const config: RequestInit = {
            ...options,
            headers: {
                ...this.defaultHeaders,
                ...(token && { Authorization: `Bearer ${token}` }),
                ...options.headers
            }
        };
        
        const url = `${this.baseURL}${endpoint}`;
        
        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                await this.handleErrorResponse(response);
            }
            
            const data: APIResponse<T> = await response.json();
            return data;
            
        } catch (error) {
            if (error instanceof APIError) {
                throw error;
            }
            
            // Network or other errors
            throw new APIError(
                0,
                'NETWORK_ERROR',
                error instanceof Error ? error.message : 'Network error occurred'
            );
        }
    }
    
    private async handleErrorResponse(response: Response): Promise<never> {
        let errorData: any = {};
        
        try {
            errorData = await response.json();
        } catch {
            // Response is not JSON
            errorData = { error: response.statusText };
        }
        
        // Handle authentication errors
        if (response.status === 401) {
            if (browser) {
                localStorage.removeItem('token');
                localStorage.removeItem('user');
                await goto('/auth');
            }
        }
        
        throw new APIError(
            response.status,
            errorData.error_code,
            errorData.error || errorData.detail || response.statusText,
            errorData.extra
        );
    }
    
    async get<T>(endpoint: string, params?: Record<string, any>): Promise<APIResponse<T>> {
        let url = endpoint;
        if (params) {
            const searchParams = new URLSearchParams();
            Object.entries(params).forEach(([key, value]) => {
                if (value !== undefined && value !== null) {
                    searchParams.append(key, String(value));
                }
            });
            url += `?${searchParams.toString()}`;
        }
        
        return this.request<T>(url);
    }
    
    async post<T>(endpoint: string, data?: any): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, {
            method: 'POST',
            body: data ? JSON.stringify(data) : undefined
        });
    }
    
    async put<T>(endpoint: string, data?: any): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, {
            method: 'PUT',
            body: data ? JSON.stringify(data) : undefined
        });
    }
    
    async patch<T>(endpoint: string, data?: any): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, {
            method: 'PATCH',
            body: data ? JSON.stringify(data) : undefined
        });
    }
    
    async delete<T>(endpoint: string): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, { method: 'DELETE' });
    }
    
    async upload<T>(
        endpoint: string, 
        formData: FormData
    ): Promise<APIResponse<T>> {
        const token = this.getAuthToken();
        
        const config: RequestInit = {
            method: 'POST',
            body: formData,
            headers: {
                ...(token && { Authorization: `Bearer ${token}` })
                // Don't set Content-Type for FormData
            }
        };
        
        const response = await fetch(`${this.baseURL}${endpoint}`, config);
        
        if (!response.ok) {
            await this.handleErrorResponse(response);
        }
        
        return response.json();
    }
}

export const apiClient = new APIClient();
```

**Resource-Specific API Clients**:
```typescript
// lib/apis/chats.ts
import { APIClient, type APIResponse, type PaginatedResponse } from './base';
import type { 
    Chat, 
    ChatCreate, 
    ChatUpdate, 
    ChatMessage,
    MessageCreate 
} from '$lib/types/chat';

export interface ChatListParams {
    page?: number;
    size?: number;
    search?: string;
    archived?: boolean;
}

export class ChatAPI extends APIClient {
    constructor() {
        super('/api/v1');
    }
    
    async getChats(params?: ChatListParams): Promise<APIResponse<PaginatedResponse<Chat>>> {
        return this.get<PaginatedResponse<Chat>>('/chats', params);
    }
    
    async getChatById(chatId: string): Promise<APIResponse<Chat>> {
        return this.get<Chat>(`/chats/${chatId}`);
    }
    
    async createChat(data: ChatCreate): Promise<APIResponse<Chat>> {
        return this.post<Chat>('/chats', data);
    }
    
    async updateChat(chatId: string, data: ChatUpdate): Promise<APIResponse<Chat>> {
        return this.put<Chat>(`/chats/${chatId}`, data);
    }
    
    async deleteChat(chatId: string): Promise<APIResponse<void>> {
        return this.delete<void>(`/chats/${chatId}`);
    }
    
    async archiveChat(chatId: string): Promise<APIResponse<Chat>> {
        return this.patch<Chat>(`/chats/${chatId}/archive`);
    }
    
    async unarchiveChat(chatId: string): Promise<APIResponse<Chat>> {
        return this.patch<Chat>(`/chats/${chatId}/unarchive`);
    }
    
    async shareChat(chatId: string, shareId: string): Promise<APIResponse<Chat>> {
        return this.patch<Chat>(`/chats/${chatId}/share`, { share_id: shareId });
    }
    
    async unshareChat(chatId: string): Promise<APIResponse<Chat>> {
        return this.patch<Chat>(`/chats/${chatId}/unshare`);
    }
    
    async getSharedChat(shareId: string): Promise<APIResponse<Chat>> {
        return this.get<Chat>(`/chats/shared/${shareId}`);
    }
    
    async addMessage(
        chatId: string, 
        data: MessageCreate
    ): Promise<APIResponse<ChatMessage>> {
        return this.post<ChatMessage>(`/chats/${chatId}/messages`, data);
    }
    
    async updateMessage(
        chatId: string, 
        messageId: string, 
        content: string
    ): Promise<APIResponse<ChatMessage>> {
        return this.put<ChatMessage>(`/chats/${chatId}/messages/${messageId}`, {
            content
        });
    }
    
    async deleteMessage(
        chatId: string, 
        messageId: string
    ): Promise<APIResponse<void>> {
        return this.delete<void>(`/chats/${chatId}/messages/${messageId}`);
    }
    
    async regenerateResponse(
        chatId: string, 
        messageId: string
    ): Promise<APIResponse<ChatMessage>> {
        return this.post<ChatMessage>(`/chats/${chatId}/messages/${messageId}/regenerate`);
    }
    
    async exportChat(chatId: string, format: 'json' | 'markdown'): Promise<Blob> {
        const response = await fetch(
            `${this.baseURL}/chats/${chatId}/export?format=${format}`,
            {
                headers: {
                    Authorization: `Bearer ${this.getAuthToken()}`
                }
            }
        );
        
        if (!response.ok) {
            throw new Error('Export failed');
        }
        
        return response.blob();
    }
    
    async importChats(file: File): Promise<APIResponse<{ imported: number; errors: string[] }>> {
        const formData = new FormData();
        formData.append('file', file);
        
        return this.upload<{ imported: number; errors: string[] }>('/chats/import', formData);
    }
}

export const chatAPI = new ChatAPI();
```

### Store Integration Patterns

**API-Integrated Stores**:
```typescript
// lib/stores/chats.ts
import { writable, derived, get } from 'svelte/store';
import type { Chat, ChatCreate, ChatUpdate } from '$lib/types/chat';
import type { PaginatedResponse } from '$lib/apis/base';
import { chatAPI } from '$lib/apis/chats';
import { toast } from 'svelte-sonner';

interface ChatState {
    chats: Chat[];
    currentChatId: string | null;
    loading: boolean;
    error: string | null;
    pagination: {
        page: number;
        size: number;
        total: number;
        hasNext: boolean;
        hasPrev: boolean;
    };
}

const initialState: ChatState = {
    chats: [],
    currentChatId: null,
    loading: false,
    error: null,
    pagination: {
        page: 1,
        size: 20,
        total: 0,
        hasNext: false,
        hasPrev: false
    }
};

// Private store
const _chatState = writable<ChatState>(initialState);

// Public read-only stores
export const chats = derived(_chatState, ($state) => $state.chats);
export const currentChatId = derived(_chatState, ($state) => $state.currentChatId);
export const currentChat = derived(
    [_chatState],
    ([$state]) => $state.chats.find(chat => chat.id === $state.currentChatId) || null
);
export const isLoading = derived(_chatState, ($state) => $state.loading);
export const error = derived(_chatState, ($state) => $state.error);
export const pagination = derived(_chatState, ($state) => $state.pagination);

// Store actions
export const chatStore = {
    // Load chats with pagination
    async loadChats(page: number = 1, size: number = 20, search?: string) {
        _chatState.update(state => ({ ...state, loading: true, error: null }));
        
        try {
            const response = await chatAPI.getChats({ page, size, search });
            
            if (response.status === 'success' && response.data) {
                _chatState.update(state => ({
                    ...state,
                    chats: response.data!.items,
                    pagination: {
                        page: response.data!.page,
                        size: response.data!.size,
                        total: response.data!.total,
                        hasNext: response.data!.has_next,
                        hasPrev: response.data!.has_prev
                    },
                    loading: false
                }));
            } else {
                throw new Error(response.error || 'Failed to load chats');
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to load chats';
            _chatState.update(state => ({ ...state, error: message, loading: false }));
            toast.error(message);
        }
    },
    
    // Load more chats (pagination)
    async loadMoreChats() {
        const state = get(_chatState);
        if (!state.pagination.hasNext || state.loading) return;
        
        _chatState.update(s => ({ ...s, loading: true }));
        
        try {
            const response = await chatAPI.getChats({
                page: state.pagination.page + 1,
                size: state.pagination.size
            });
            
            if (response.status === 'success' && response.data) {
                _chatState.update(s => ({
                    ...s,
                    chats: [...s.chats, ...response.data!.items],
                    pagination: {
                        page: response.data!.page,
                        size: response.data!.size,
                        total: response.data!.total,
                        hasNext: response.data!.has_next,
                        hasPrev: response.data!.has_prev
                    },
                    loading: false
                }));
            }
        } catch (error) {
            _chatState.update(s => ({ 
                ...s, 
                error: error instanceof Error ? error.message : 'Failed to load more chats',
                loading: false 
            }));
        }
    },
    
    // Create new chat
    async createChat(data: ChatCreate): Promise<Chat | null> {
        try {
            const response = await chatAPI.createChat(data);
            
            if (response.status === 'success' && response.data) {
                const newChat = response.data;
                
                _chatState.update(state => ({
                    ...state,
                    chats: [newChat, ...state.chats],
                    currentChatId: newChat.id,
                    pagination: {
                        ...state.pagination,
                        total: state.pagination.total + 1
                    }
                }));
                
                toast.success('Chat created successfully');
                return newChat;
            } else {
                throw new Error(response.error || 'Failed to create chat');
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to create chat';
            toast.error(message);
            return null;
        }
    },
    
    // Update chat
    async updateChat(chatId: string, data: ChatUpdate): Promise<Chat | null> {
        try {
            const response = await chatAPI.updateChat(chatId, data);
            
            if (response.status === 'success' && response.data) {
                const updatedChat = response.data;
                
                _chatState.update(state => ({
                    ...state,
                    chats: state.chats.map(chat => 
                        chat.id === chatId ? updatedChat : chat
                    )
                }));
                
                toast.success('Chat updated successfully');
                return updatedChat;
            } else {
                throw new Error(response.error || 'Failed to update chat');
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to update chat';
            toast.error(message);
            return null;
        }
    },
    
    // Delete chat
    async deleteChat(chatId: string): Promise<boolean> {
        try {
            const response = await chatAPI.deleteChat(chatId);
            
            if (response.status === 'success') {
                _chatState.update(state => ({
                    ...state,
                    chats: state.chats.filter(chat => chat.id !== chatId),
                    currentChatId: state.currentChatId === chatId ? null : state.currentChatId,
                    pagination: {
                        ...state.pagination,
                        total: Math.max(0, state.pagination.total - 1)
                    }
                }));
                
                toast.success('Chat deleted successfully');
                return true;
            } else {
                throw new Error(response.error || 'Failed to delete chat');
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to delete chat';
            toast.error(message);
            return false;
        }
    },
    
    // Set current chat
    setCurrentChat(chatId: string | null) {
        _chatState.update(state => ({ ...state, currentChatId: chatId }));
    },
    
    // Load specific chat
    async loadChat(chatId: string): Promise<Chat | null> {
        try {
            const response = await chatAPI.getChatById(chatId);
            
            if (response.status === 'success' && response.data) {
                const chat = response.data;
                
                _chatState.update(state => {
                    const exists = state.chats.some(c => c.id === chatId);
                    const chats = exists 
                        ? state.chats.map(c => c.id === chatId ? chat : c)
                        : [...state.chats, chat];
                    
                    return {
                        ...state,
                        chats,
                        currentChatId: chatId
                    };
                });
                
                return chat;
            } else {
                throw new Error(response.error || 'Chat not found');
            }
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to load chat';
            toast.error(message);
            return null;
        }
    },
    
    // Clear store
    clear() {
        _chatState.set(initialState);
    }
};
```

### Error Handling Patterns

**Consistent Error Handling**:
```typescript
// lib/utils/error-handling.ts
import { toast } from 'svelte-sonner';
import { APIError } from '$lib/apis/base';
import { goto } from '$app/navigation';

export interface ErrorHandlerOptions {
    showToast?: boolean;
    redirectOnAuth?: boolean;
    customMessage?: string;
    onError?: (error: APIError) => void;
}

export class ErrorHandler {
    static handle(error: unknown, options: ErrorHandlerOptions = {}) {
        const {
            showToast = true,
            redirectOnAuth = true,
            customMessage,
            onError
        } = options;
        
        let apiError: APIError;
        
        if (error instanceof APIError) {
            apiError = error;
        } else if (error instanceof Error) {
            apiError = new APIError(0, 'UNKNOWN_ERROR', error.message);
        } else {
            apiError = new APIError(0, 'UNKNOWN_ERROR', 'An unknown error occurred');
        }
        
        // Handle specific error types
        switch (apiError.status) {
            case 401:
                if (redirectOnAuth) {
                    localStorage.removeItem('token');
                    localStorage.removeItem('user');
                    goto('/auth');
                }
                break;
            case 403:
                if (showToast) {
                    toast.error(customMessage || 'Access denied');
                }
                break;
            case 404:
                if (showToast) {
                    toast.error(customMessage || 'Resource not found');
                }
                break;
            case 422:
                if (showToast) {
                    toast.error(customMessage || 'Validation error');
                }
                break;
            case 429:
                if (showToast) {
                    toast.error('Too many requests. Please try again later.');
                }
                break;
            case 500:
                if (showToast) {
                    toast.error('Server error. Please try again later.');
                }
                break;
            default:
                if (showToast) {
                    toast.error(customMessage || apiError.message);
                }
        }
        
        // Custom error handler
        if (onError) {
            onError(apiError);
        }
        
        // Log error for debugging
        console.error('API Error:', {
            status: apiError.status,
            error_code: apiError.error_code,
            message: apiError.message,
            extra: apiError.extra
        });
        
        return apiError;
    }
    
    static async withErrorHandling<T>(
        operation: () => Promise<T>,
        options: ErrorHandlerOptions = {}
    ): Promise<T | null> {
        try {
            return await operation();
        } catch (error) {
            ErrorHandler.handle(error, options);
            return null;
        }
    }
}

// Usage in stores and components
export const handleAsyncOperation = async <T>(
    operation: () => Promise<T>,
    options?: ErrorHandlerOptions
): Promise<T | null> => {
    return ErrorHandler.withErrorHandling(operation, options);
};

// Usage examples
await handleAsyncOperation(
    () => chatAPI.createChat(data),
    {
        customMessage: 'Failed to create chat',
        onError: (error) => {
            // Custom handling
            if (error.error_code === 'QUOTA_EXCEEDED') {
                // Handle quota error specifically
            }
        }
    }
);
```

This comprehensive API pattern guide ensures consistent, type-safe, and robust API integration between the Open WebUI frontend and backend, with proper error handling, authentication, and performance optimization.