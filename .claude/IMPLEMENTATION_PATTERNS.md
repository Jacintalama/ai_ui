# IMPLEMENTATION_PATTERNS.md - Open WebUI Development Patterns

Implementation patterns and best practices for feature development in Open WebUI.

## Frontend Implementation Patterns

### SvelteKit Component Development

**Component Structure Pattern**:
```typescript
<!-- ChatMessage.svelte -->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import type { ChatMessage } from '$lib/types';
    
    export let message: ChatMessage;
    export let isUser: boolean = false;
    export let model: string | null = null;
    
    const dispatch = createEventDispatcher<{
        edit: { messageId: string };
        delete: { messageId: string };
        regenerate: { messageId: string };
    }>();
    
    let isEditing = false;
    let editContent = message.content;
    
    // Reactive statements
    $: messageClasses = `chat-message ${isUser ? 'chat-message--user' : 'chat-message--assistant'}`;
    $: canEdit = isUser && !message.streaming;
    
    // Event handlers
    function handleEdit() {
        dispatch('edit', { messageId: message.id });
        isEditing = true;
    }
    
    function handleSave() {
        // Validation and save logic
        if (editContent.trim()) {
            message.content = editContent;
            isEditing = false;
        }
    }
</script>

<div class={messageClasses}>
    {#if isEditing}
        <textarea 
            bind:value={editContent}
            class="w-full p-2 border rounded resize-none focus:ring-2 focus:ring-blue-500"
            on:keydown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSave();
                }
            }}
        />
        <div class="flex gap-2 mt-2">
            <button on:click={handleSave} class="btn-primary btn-sm">Save</button>
            <button on:click={() => isEditing = false} class="btn-secondary btn-sm">Cancel</button>
        </div>
    {:else}
        <div class="prose dark:prose-invert">
            {@html message.content}
        </div>
        {#if canEdit}
            <div class="flex gap-2 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button on:click={handleEdit} class="btn-ghost btn-sm">Edit</button>
                <button on:click={() => dispatch('delete', { messageId: message.id })} class="btn-ghost btn-sm">Delete</button>
                {#if !isUser}
                    <button on:click={() => dispatch('regenerate', { messageId: message.id })} class="btn-ghost btn-sm">Regenerate</button>
                {/if}
            </div>
        {/if}
    {/if}
</div>
```

**Store-based State Management**:
```typescript
// lib/stores/chat.ts
import { writable, derived, get } from 'svelte/store';
import type { ChatMessage, Chat } from '$lib/types';
import { chatAPI } from '$lib/apis/chats';

// Private stores
const _chats = writable<Chat[]>([]);
const _currentChatId = writable<string | null>(null);
const _isLoading = writable(false);

// Public stores
export const chats = { subscribe: _chats.subscribe };
export const currentChatId = { subscribe: _currentChatId.subscribe };
export const isLoading = { subscribe: _isLoading.subscribe };

// Derived stores
export const currentChat = derived(
    [_chats, _currentChatId],
    ([$chats, $currentChatId]) => {
        return $chats.find(chat => chat.id === $currentChatId) || null;
    }
);

export const currentMessages = derived(
    currentChat,
    ($currentChat) => $currentChat?.messages || []
);

// Actions
export const chatStore = {
    // Load chats from API
    async loadChats() {
        _isLoading.set(true);
        try {
            const response = await chatAPI.getAll();
            _chats.set(response.data);
        } catch (error) {
            console.error('Failed to load chats:', error);
        } finally {
            _isLoading.set(false);
        }
    },
    
    // Create new chat
    async createChat(title: string = 'New Chat') {
        try {
            const response = await chatAPI.create({ title });
            const newChat = response.data;
            
            _chats.update(chats => [...chats, newChat]);
            _currentChatId.set(newChat.id);
            
            return newChat;
        } catch (error) {
            console.error('Failed to create chat:', error);
            throw error;
        }
    },
    
    // Add message to current chat
    async addMessage(content: string, role: 'user' | 'assistant' = 'user') {
        const chatId = get(_currentChatId);
        if (!chatId) return;
        
        const message: ChatMessage = {
            id: crypto.randomUUID(),
            content,
            role,
            timestamp: Date.now()
        };
        
        _chats.update(chats => 
            chats.map(chat => 
                chat.id === chatId 
                    ? { ...chat, messages: [...chat.messages, message] }
                    : chat
            )
        );
        
        // Persist to API
        try {
            await chatAPI.addMessage(chatId, message);
        } catch (error) {
            console.error('Failed to persist message:', error);
        }
        
        return message;
    },
    
    // Set current chat
    setCurrentChat(chatId: string | null) {
        _currentChatId.set(chatId);
    },
    
    // Delete chat
    async deleteChat(chatId: string) {
        try {
            await chatAPI.delete(chatId);
            
            _chats.update(chats => chats.filter(chat => chat.id !== chatId));
            
            if (get(_currentChatId) === chatId) {
                _currentChatId.set(null);
            }
        } catch (error) {
            console.error('Failed to delete chat:', error);
            throw error;
        }
    }
};
```

**Form Actions Pattern**:
```typescript
// routes/(app)/+page.server.ts
import type { Actions } from './$types';
import { fail } from '@sveltejs/kit';
import { chatAPI } from '$lib/apis/chats';

export const actions: Actions = {
    sendMessage: async ({ request, locals }) => {
        const data = await request.formData();
        const message = data.get('message') as string;
        const chatId = data.get('chatId') as string;
        
        // Validation
        if (!message?.trim()) {
            return fail(400, { message, error: 'Message cannot be empty' });
        }
        
        if (!locals.user) {
            return fail(401, { message, error: 'Authentication required' });
        }
        
        try {
            // Send to API
            const response = await chatAPI.sendMessage({
                chatId,
                content: message,
                userId: locals.user.id
            });
            
            return { 
                success: true, 
                message: response.data 
            };
        } catch (error) {
            console.error('Send message error:', error);
            return fail(500, { 
                message, 
                error: 'Failed to send message' 
            });
        }
    },
    
    deleteMessage: async ({ request, locals }) => {
        const data = await request.formData();
        const messageId = data.get('messageId') as string;
        
        if (!locals.user) {
            return fail(401, { error: 'Authentication required' });
        }
        
        try {
            await chatAPI.deleteMessage(messageId, locals.user.id);
            return { success: true };
        } catch (error) {
            return fail(500, { error: 'Failed to delete message' });
        }
    }
};
```

### API Client Patterns

**Type-safe API Client**:
```typescript
// lib/apis/base.ts
class APIClient {
    private baseURL: string;
    private defaultHeaders: HeadersInit;
    
    constructor(baseURL: string = '/api/v1') {
        this.baseURL = baseURL;
        this.defaultHeaders = {
            'Content-Type': 'application/json'
        };
    }
    
    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<APIResponse<T>> {
        const token = localStorage.getItem('token');
        
        const config: RequestInit = {
            ...options,
            headers: {
                ...this.defaultHeaders,
                ...(token && { Authorization: `Bearer ${token}` }),
                ...options.headers
            }
        };
        
        const response = await fetch(`${this.baseURL}${endpoint}`, config);
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new APIError(response.status, error.detail || 'Request failed');
        }
        
        return response.json();
    }
    
    async get<T>(endpoint: string): Promise<APIResponse<T>> {
        return this.request<T>(endpoint);
    }
    
    async post<T>(endpoint: string, data: unknown): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    async put<T>(endpoint: string, data: unknown): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }
    
    async delete<T>(endpoint: string): Promise<APIResponse<T>> {
        return this.request<T>(endpoint, { method: 'DELETE' });
    }
}

export const apiClient = new APIClient();

// Specific API clients
export class ChatAPI extends APIClient {
    async getAll(): Promise<APIResponse<Chat[]>> {
        return this.get<Chat[]>('/chats');
    }
    
    async getById(id: string): Promise<APIResponse<Chat>> {
        return this.get<Chat>(`/chats/${id}`);
    }
    
    async create(data: Partial<Chat>): Promise<APIResponse<Chat>> {
        return this.post<Chat>('/chats', data);
    }
    
    async update(id: string, data: Partial<Chat>): Promise<APIResponse<Chat>> {
        return this.put<Chat>(`/chats/${id}`, data);
    }
    
    async delete(id: string): Promise<APIResponse<void>> {
        return this.delete<void>(`/chats/${id}`);
    }
    
    async sendMessage(data: {
        chatId: string;
        content: string;
        userId: string;
    }): Promise<APIResponse<ChatMessage>> {
        return this.post<ChatMessage>(`/chats/${data.chatId}/messages`, {
            content: data.content,
            role: 'user'
        });
    }
}

export const chatAPI = new ChatAPI();
```

**WebSocket Integration**:
```typescript
// lib/websocket.ts
import { writable } from 'svelte/store';
import type { ChatMessage } from '$lib/types';

interface WebSocketMessage {
    type: 'chat_chunk' | 'chat_complete' | 'error';
    data: any;
}

class ChatWebSocket {
    private ws: WebSocket | null = null;
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 5;
    private reconnectDelay = 1000;
    
    public connected = writable(false);
    public error = writable<string | null>(null);
    
    connect(userId: string) {
        try {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/${userId}`;
            
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.connected.set(true);
                this.error.set(null);
                this.reconnectAttempts = 0;
            };
            
            this.ws.onclose = (event) => {
                console.log('WebSocket disconnected:', event.code);
                this.connected.set(false);
                
                if (event.code !== 1000) { // Not a normal closure
                    this.reconnect(userId);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.error.set('Connection error');
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const message: WebSocketMessage = JSON.parse(event.data);
                    this.handleMessage(message);
                } catch (error) {
                    console.error('Failed to parse WebSocket message:', error);
                }
            };
            
        } catch (error) {
            console.error('Failed to connect WebSocket:', error);
            this.error.set('Failed to connect');
        }
    }
    
    private handleMessage(message: WebSocketMessage) {
        switch (message.type) {
            case 'chat_chunk':
                // Handle streaming chat chunk
                this.appendToCurrentMessage(message.data.chunk);
                break;
            case 'chat_complete':
                // Handle completed message
                this.finalizeCurrentMessage(message.data.message);
                break;
            case 'error':
                this.error.set(message.data.error);
                break;
        }
    }
    
    private reconnect(userId: string) {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.error.set('Failed to reconnect');
            return;
        }
        
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        
        setTimeout(() => {
            console.log(`Reconnecting... (attempt ${this.reconnectAttempts})`);
            this.connect(userId);
        }, delay);
    }
    
    send(message: any) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('WebSocket not connected');
        }
    }
    
    disconnect() {
        if (this.ws) {
            this.ws.close(1000); // Normal closure
            this.ws = null;
        }
    }
}

export const chatWebSocket = new ChatWebSocket();
```

## Backend Implementation Patterns

### FastAPI Router Patterns

**Dependency-Driven Route Structure**:
```python
# routers/chats.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from ..database import get_db
from ..auth import get_current_user, get_admin_user
from ..models import User, Chat
from ..schemas import ChatCreate, ChatResponse, ChatUpdate
from ..services.chat_service import ChatService

router = APIRouter(prefix="/chats", tags=["chats"])

@router.get("", response_model=List[ChatResponse])
async def get_user_chats(
    skip: int = 0,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all chats for the current user"""
    chat_service = ChatService(db)
    chats = await chat_service.get_user_chats(
        user_id=current_user.id,
        skip=skip,
        limit=limit
    )
    return chats

@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    chat_data: ChatCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new chat"""
    chat_service = ChatService(db)
    
    # Validate permissions
    if not current_user.permissions.chat.create:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat creation not permitted"
        )
    
    try:
        chat = await chat_service.create_chat(
            title=chat_data.title,
            user_id=current_user.id,
            model_id=chat_data.model_id
        )
        return chat
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create chat: {str(e)}"
        )

@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific chat by ID"""
    chat_service = ChatService(db)
    
    chat = await chat_service.get_chat_by_id(chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )
    
    # Check ownership or admin access
    if chat.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    return chat

@router.put("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: str,
    chat_update: ChatUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a chat"""
    chat_service = ChatService(db)
    
    # Verify ownership
    chat = await chat_service.get_chat_by_id(chat_id)
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )
    
    # Check edit permission
    if not current_user.permissions.chat.edit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat editing not permitted"
        )
    
    updated_chat = await chat_service.update_chat(chat_id, chat_update.dict(exclude_unset=True))
    return updated_chat

@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a chat"""
    chat_service = ChatService(db)
    
    # Verify ownership or admin access
    chat = await chat_service.get_chat_by_id(chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found"
        )
    
    if chat.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Check delete permission
    if not current_user.permissions.chat.delete:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat deletion not permitted"
        )
    
    await chat_service.delete_chat(chat_id)

# WebSocket endpoint
@router.websocket("/{chat_id}/ws")
async def chat_websocket(
    websocket: WebSocket,
    chat_id: str,
    current_user: User = Depends(get_current_user_ws),
    db: AsyncSession = Depends(get_db)
):
    """WebSocket endpoint for real-time chat"""
    await websocket.accept()
    
    chat_service = ChatService(db)
    
    # Verify chat access
    chat = await chat_service.get_chat_by_id(chat_id)
    if not chat or chat.user_id != current_user.id:
        await websocket.close(code=4003, reason="Access denied")
        return
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            # Process message
            if data["type"] == "chat_message":
                await handle_chat_message(websocket, chat, data["content"], current_user)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for chat {chat_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await websocket.close(code=4000, reason="Internal error")
```

### Service Layer Patterns

**Business Logic Separation**:
```python
# services/chat_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime

from ..models import Chat, User, Message
from ..schemas import ChatCreate, MessageCreate
from .ai_service import AIService

class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai_service = AIService()
    
    async def create_chat(
        self, 
        title: str, 
        user_id: str, 
        model_id: Optional[str] = None
    ) -> Chat:
        """Create a new chat for a user"""
        chat = Chat(
            id=str(uuid.uuid4()),
            title=title,
            user_id=user_id,
            model_id=model_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.db.add(chat)
        await self.db.commit()
        await self.db.refresh(chat)
        
        return chat
    
    async def get_user_chats(
        self, 
        user_id: str, 
        skip: int = 0, 
        limit: int = 50
    ) -> List[Chat]:
        """Get paginated chats for a user"""
        stmt = (
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(Chat.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_chat_by_id(self, chat_id: str) -> Optional[Chat]:
        """Get chat by ID with messages"""
        stmt = select(Chat).where(Chat.id == chat_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def add_message_to_chat(
        self, 
        chat_id: str, 
        content: str, 
        role: str = "user"
    ) -> Message:
        """Add a message to a chat"""
        message = Message(
            id=str(uuid.uuid4()),
            chat_id=chat_id,
            content=content,
            role=role,
            timestamp=datetime.utcnow()
        )
        
        self.db.add(message)
        
        # Update chat's updated_at timestamp
        stmt = (
            update(Chat)
            .where(Chat.id == chat_id)
            .values(updated_at=datetime.utcnow())
        )
        await self.db.execute(stmt)
        
        await self.db.commit()
        await self.db.refresh(message)
        
        return message
    
    async def generate_response(
        self, 
        chat_id: str, 
        user_message: str,
        model_id: str
    ) -> AsyncIterator[str]:
        """Generate AI response for a chat message"""
        # Get chat history
        chat = await self.get_chat_with_messages(chat_id)
        if not chat:
            raise ValueError("Chat not found")
        
        # Build message history for AI
        messages = []
        for msg in chat.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        
        # Add new user message
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        # Generate response stream
        response_content = ""
        async for chunk in self.ai_service.generate_stream(messages, model_id):
            response_content += chunk
            yield chunk
        
        # Save AI response to database
        await self.add_message_to_chat(
            chat_id=chat_id,
            content=response_content,
            role="assistant"
        )
    
    async def update_chat(self, chat_id: str, update_data: Dict[str, Any]) -> Chat:
        """Update chat properties"""
        stmt = (
            update(Chat)
            .where(Chat.id == chat_id)
            .values(**update_data, updated_at=datetime.utcnow())
        )
        
        await self.db.execute(stmt)
        await self.db.commit()
        
        return await self.get_chat_by_id(chat_id)
    
    async def delete_chat(self, chat_id: str) -> None:
        """Delete a chat and all its messages"""
        # Delete messages first (if not handled by cascade)
        await self.db.execute(delete(Message).where(Message.chat_id == chat_id))
        
        # Delete chat
        await self.db.execute(delete(Chat).where(Chat.id == chat_id))
        
        await self.db.commit()
    
    async def get_chat_with_messages(self, chat_id: str) -> Optional[Chat]:
        """Get chat with all its messages loaded"""
        stmt = (
            select(Chat)
            .where(Chat.id == chat_id)
            .options(selectinload(Chat.messages))
        )
        
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
```

### AI Provider Integration Pattern

**Abstraction Layer for Multiple Providers**:
```python
# services/ai_service.py
from abc import ABC, abstractmethod
from typing import List, Dict, AsyncIterator, Optional
import httpx
import openai
from enum import Enum

class AIProvider(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

class BaseAIProvider(ABC):
    @abstractmethod
    async def generate_stream(
        self, 
        messages: List[Dict[str, str]], 
        model: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """Generate streaming response"""
        pass
    
    @abstractmethod
    async def generate_complete(
        self, 
        messages: List[Dict[str, str]], 
        model: str,
        **kwargs
    ) -> str:
        """Generate complete response"""
        pass
    
    @abstractmethod
    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models"""
        pass

class OllamaProvider(BaseAIProvider):
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url)
    
    async def generate_stream(
        self, 
        messages: List[Dict[str, str]], 
        model: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream response from Ollama"""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs
        }
        
        async with self.client.stream(
            "POST", 
            "/api/chat", 
            json=payload
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            yield data["message"]["content"]
                    except json.JSONDecodeError:
                        continue
    
    async def generate_complete(
        self, 
        messages: List[Dict[str, str]], 
        model: str,
        **kwargs
    ) -> str:
        """Complete response from Ollama"""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            **kwargs
        }
        
        response = await self.client.post("/api/chat", json=payload)
        response.raise_for_status()
        
        data = response.json()
        return data["message"]["content"]
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List Ollama models"""
        response = await self.client.get("/api/tags")
        response.raise_for_status()
        
        data = response.json()
        return [
            {
                "id": model["name"],
                "name": model["name"],
                "provider": "ollama",
                "size": model.get("size", 0),
                "modified_at": model.get("modified_at")
            }
            for model in data.get("models", [])
        ]

class OpenAIProvider(BaseAIProvider):
    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )
    
    async def generate_stream(
        self, 
        messages: List[Dict[str, str]], 
        model: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream response from OpenAI"""
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            **kwargs
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def generate_complete(
        self, 
        messages: List[Dict[str, str]], 
        model: str,
        **kwargs
    ) -> str:
        """Complete response from OpenAI"""
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            **kwargs
        )
        
        return response.choices[0].message.content
    
    async def list_models(self) -> List[Dict[str, Any]]:
        """List OpenAI models"""
        models = await self.client.models.list()
        
        return [
            {
                "id": model.id,
                "name": model.id,
                "provider": "openai",
                "created": model.created
            }
            for model in models.data
            if model.id.startswith(("gpt-", "text-"))
        ]

class AIService:
    def __init__(self):
        self.providers: Dict[str, BaseAIProvider] = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize available AI providers"""
        # Ollama
        if settings.OLLAMA_BASE_URL:
            self.providers["ollama"] = OllamaProvider(settings.OLLAMA_BASE_URL)
        
        # OpenAI
        if settings.OPENAI_API_KEY:
            self.providers["openai"] = OpenAIProvider(settings.OPENAI_API_KEY)
        
        # Add more providers as needed
    
    def get_provider_for_model(self, model_id: str) -> BaseAIProvider:
        """Get the appropriate provider for a model"""
        # Logic to determine provider based on model_id
        if model_id.startswith("gpt-"):
            return self.providers["openai"]
        elif ":" in model_id:  # Ollama format like "llama2:7b"
            return self.providers["ollama"]
        
        # Default to first available provider
        if self.providers:
            return next(iter(self.providers.values()))
        
        raise ValueError("No AI providers configured")
    
    async def generate_stream(
        self, 
        messages: List[Dict[str, str]], 
        model_id: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """Generate streaming response using appropriate provider"""
        provider = self.get_provider_for_model(model_id)
        async for chunk in provider.generate_stream(messages, model_id, **kwargs):
            yield chunk
    
    async def generate_complete(
        self, 
        messages: List[Dict[str, str]], 
        model_id: str,
        **kwargs
    ) -> str:
        """Generate complete response using appropriate provider"""
        provider = self.get_provider_for_model(model_id)
        return await provider.generate_complete(messages, model_id, **kwargs)
    
    async def list_all_models(self) -> List[Dict[str, Any]]:
        """List models from all providers"""
        all_models = []
        
        for provider_name, provider in self.providers.items():
            try:
                models = await provider.list_models()
                all_models.extend(models)
            except Exception as e:
                logger.warning(f"Failed to list models from {provider_name}: {e}")
        
        return all_models
```

This implementation pattern provides:

1. **Clear separation of concerns** between frontend components, API clients, and backend services
2. **Type safety** throughout the application with TypeScript interfaces
3. **Consistent error handling** and validation patterns
4. **Modular architecture** that supports multiple AI providers
5. **Real-time functionality** through WebSocket integration
6. **Scalable state management** using Svelte stores
7. **Dependency injection** for testability and maintainability
8. **Proper authentication and authorization** patterns

These patterns ensure maintainable, scalable, and robust feature development in Open WebUI.