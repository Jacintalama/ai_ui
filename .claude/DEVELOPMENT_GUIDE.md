# DEVELOPMENT_GUIDE.md - Open WebUI Development Guidelines

Comprehensive development guidelines for building features in Open WebUI.

## Development Workflow

### Getting Started

**Environment Setup**:
```bash
# Clone repository
git clone <repository-url>
cd ai_ui

# Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend setup  
cd ..
npm install

# Environment configuration
cp .env.example .env
# Edit .env with your configuration
```

**Development Commands**:
```bash
# Frontend development
npm run dev          # Start dev server with hot reload
npm run build        # Build for production
npm run preview      # Preview production build
npm run lint         # Run ESLint
npm run format       # Format with Prettier
npm run type-check   # TypeScript type checking

# Backend development
cd backend
uvicorn open_webui.main:app --reload --host 0.0.0.0 --port 8080

# Database operations
alembic upgrade head     # Apply migrations
alembic revision --autogenerate -m "Description"  # Create migration

# Testing
npm run test        # Frontend tests
pytest             # Backend tests
```

### Project Structure Understanding

**Frontend Structure**:
```
src/
├── lib/                    # Shared utilities and components
│   ├── components/         # Reusable components
│   │   ├── chat/          # Chat-related components
│   │   ├── common/        # Generic UI components
│   │   └── layout/        # Layout components
│   ├── stores/            # Svelte stores
│   ├── apis/              # API client modules
│   ├── types/             # TypeScript type definitions
│   ├── utils/             # Utility functions
│   └── constants.ts       # Application constants
├── routes/                # File-based routing
│   ├── (app)/            # Main application routes
│   ├── auth/             # Authentication routes
│   └── api/              # API endpoints (if any)
├── app.html              # HTML template
└── app.css               # Global styles
```

**Backend Structure**:
```
backend/open_webui/
├── main.py               # FastAPI application entry
├── routers/              # API route handlers
│   ├── auth.py          # Authentication routes
│   ├── chats.py         # Chat management
│   ├── models.py        # AI model management
│   └── users.py         # User management
├── models/               # Database models
├── schemas/              # Pydantic schemas
├── services/             # Business logic layer
├── database.py           # Database configuration
├── auth.py              # Authentication utilities
├── config.py            # Configuration settings
└── utils/               # Utility functions
```

## Feature Development Guidelines

### Frontend Feature Development

**1. Component Development Process**:

```typescript
// 1. Define types first
// lib/types/feature.ts
export interface FeatureItem {
    id: string;
    name: string;
    description: string;
    enabled: boolean;
    created_at: string;
    updated_at: string;
}

export interface FeatureCreate {
    name: string;
    description: string;
    enabled?: boolean;
}

export interface FeatureUpdate {
    name?: string;
    description?: string;
    enabled?: boolean;
}
```

```typescript
// 2. Create API client
// lib/apis/features.ts
import { APIClient } from './base';
import type { FeatureItem, FeatureCreate, FeatureUpdate } from '$lib/types/feature';

export class FeatureAPI extends APIClient {
    async getAll(): Promise<APIResponse<FeatureItem[]>> {
        return this.get<FeatureItem[]>('/features');
    }
    
    async getById(id: string): Promise<APIResponse<FeatureItem>> {
        return this.get<FeatureItem>(`/features/${id}`);
    }
    
    async create(data: FeatureCreate): Promise<APIResponse<FeatureItem>> {
        return this.post<FeatureItem>('/features', data);
    }
    
    async update(id: string, data: FeatureUpdate): Promise<APIResponse<FeatureItem>> {
        return this.put<FeatureItem>(`/features/${id}`, data);
    }
    
    async delete(id: string): Promise<APIResponse<void>> {
        return this.delete<void>(`/features/${id}`);
    }
}

export const featureAPI = new FeatureAPI();
```

```typescript
// 3. Create store for state management
// lib/stores/features.ts
import { writable, derived, get } from 'svelte/store';
import type { FeatureItem } from '$lib/types/feature';
import { featureAPI } from '$lib/apis/features';
import { toast } from 'svelte-sonner';

const _features = writable<FeatureItem[]>([]);
const _loading = writable(false);
const _error = writable<string | null>(null);

export const features = { subscribe: _features.subscribe };
export const featuresLoading = { subscribe: _loading.subscribe };
export const featuresError = { subscribe: _error.subscribe };

export const enabledFeatures = derived(
    _features,
    ($features) => $features.filter(f => f.enabled)
);

export const featureStore = {
    async loadFeatures() {
        _loading.set(true);
        _error.set(null);
        
        try {
            const response = await featureAPI.getAll();
            _features.set(response.data);
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to load features';
            _error.set(message);
            toast.error(message);
        } finally {
            _loading.set(false);
        }
    },
    
    async createFeature(data: FeatureCreate) {
        try {
            const response = await featureAPI.create(data);
            _features.update(features => [...features, response.data]);
            toast.success('Feature created successfully');
            return response.data;
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to create feature';
            toast.error(message);
            throw error;
        }
    },
    
    async updateFeature(id: string, data: FeatureUpdate) {
        try {
            const response = await featureAPI.update(id, data);
            _features.update(features => 
                features.map(f => f.id === id ? response.data : f)
            );
            toast.success('Feature updated successfully');
            return response.data;
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to update feature';
            toast.error(message);
            throw error;
        }
    },
    
    async deleteFeature(id: string) {
        try {
            await featureAPI.delete(id);
            _features.update(features => features.filter(f => f.id !== id));
            toast.success('Feature deleted successfully');
        } catch (error) {
            const message = error instanceof Error ? error.message : 'Failed to delete feature';
            toast.error(message);
            throw error;
        }
    }
};
```

```svelte
<!-- 4. Create components -->
<!-- lib/components/features/FeatureCard.svelte -->
<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import type { FeatureItem } from '$lib/types/feature';
    
    export let feature: FeatureItem;
    export let canEdit = false;
    export let canDelete = false;
    
    const dispatch = createEventDispatcher<{
        edit: { feature: FeatureItem };
        delete: { feature: FeatureItem };
        toggle: { feature: FeatureItem; enabled: boolean };
    }>();
    
    function handleToggle() {
        dispatch('toggle', { feature, enabled: !feature.enabled });
    }
    
    function handleEdit() {
        dispatch('edit', { feature });
    }
    
    function handleDelete() {
        if (confirm(`Are you sure you want to delete "${feature.name}"?`)) {
            dispatch('delete', { feature });
        }
    }
</script>

<div class="card bg-white dark:bg-gray-800 shadow-sm rounded-lg p-6">
    <div class="flex items-start justify-between mb-4">
        <div class="flex-1">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white">
                {feature.name}
            </h3>
            <p class="text-sm text-gray-600 dark:text-gray-300 mt-1">
                {feature.description}
            </p>
        </div>
        
        <div class="flex items-center gap-2 ml-4">
            <!-- Enable/Disable toggle -->
            <label class="relative inline-flex items-center cursor-pointer">
                <input
                    type="checkbox"
                    class="sr-only peer"
                    checked={feature.enabled}
                    on:change={handleToggle}
                />
                <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 dark:peer-focus:ring-blue-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-blue-600"></div>
            </label>
            
            <!-- Action buttons -->
            {#if canEdit}
                <button 
                    on:click={handleEdit}
                    class="btn-ghost btn-sm text-gray-500 hover:text-gray-700"
                    title="Edit feature"
                >
                    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/>
                    </svg>
                </button>
            {/if}
            
            {#if canDelete}
                <button 
                    on:click={handleDelete}
                    class="btn-ghost btn-sm text-red-500 hover:text-red-700"
                    title="Delete feature"
                >
                    <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                    </svg>
                </button>
            {/if}
        </div>
    </div>
    
    <div class="flex items-center justify-between text-xs text-gray-500">
        <span>Created: {new Date(feature.created_at).toLocaleDateString()}</span>
        <span class="px-2 py-1 rounded-full text-xs {feature.enabled ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'}">
            {feature.enabled ? 'Enabled' : 'Disabled'}
        </span>
    </div>
</div>
```

```svelte
<!-- 5. Create page component -->
<!-- routes/(app)/features/+page.svelte -->
<script lang="ts">
    import { onMount } from 'svelte';
    import { featureStore, features, featuresLoading } from '$lib/stores/features';
    import { user } from '$lib/stores/user';
    import FeatureCard from '$lib/components/features/FeatureCard.svelte';
    import FeatureModal from '$lib/components/features/FeatureModal.svelte';
    import type { FeatureItem } from '$lib/types/feature';
    
    let showCreateModal = false;
    let editingFeature: FeatureItem | null = null;
    
    onMount(() => {
        featureStore.loadFeatures();
    });
    
    async function handleToggle(event: CustomEvent) {
        const { feature, enabled } = event.detail;
        await featureStore.updateFeature(feature.id, { enabled });
    }
    
    function handleEdit(event: CustomEvent) {
        editingFeature = event.detail.feature;
    }
    
    async function handleDelete(event: CustomEvent) {
        const { feature } = event.detail;
        await featureStore.deleteFeature(feature.id);
    }
    
    $: isAdmin = $user?.role === 'admin';
    $: canManageFeatures = isAdmin;
</script>

<svelte:head>
    <title>Features - Open WebUI</title>
</svelte:head>

<div class="container mx-auto px-4 py-8">
    <div class="flex items-center justify-between mb-8">
        <div>
            <h1 class="text-3xl font-bold text-gray-900 dark:text-white">Features</h1>
            <p class="text-gray-600 dark:text-gray-300 mt-2">
                Manage application features and settings
            </p>
        </div>
        
        {#if canManageFeatures}
            <button
                on:click={() => showCreateModal = true}
                class="btn-primary"
            >
                <svg class="w-5 h-5 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
                </svg>
                Create Feature
            </button>
        {/if}
    </div>
    
    {#if $featuresLoading}
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {#each Array(6) as _}
                <div class="card bg-white dark:bg-gray-800 shadow-sm rounded-lg p-6 animate-pulse">
                    <div class="h-4 bg-gray-200 dark:bg-gray-700 rounded mb-2"></div>
                    <div class="h-3 bg-gray-200 dark:bg-gray-700 rounded w-2/3"></div>
                </div>
            {/each}
        </div>
    {:else if $features.length > 0}
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {#each $features as feature (feature.id)}
                <FeatureCard 
                    {feature}
                    canEdit={canManageFeatures}
                    canDelete={canManageFeatures}
                    on:toggle={handleToggle}
                    on:edit={handleEdit}
                    on:delete={handleDelete}
                />
            {/each}
        </div>
    {:else}
        <div class="text-center py-12">
            <svg class="w-12 h-12 text-gray-400 mx-auto mb-4" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"/>
            </svg>
            <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2">No features found</h3>
            <p class="text-gray-600 dark:text-gray-300 mb-4">Get started by creating your first feature.</p>
            {#if canManageFeatures}
                <button
                    on:click={() => showCreateModal = true}
                    class="btn-primary"
                >
                    Create Feature
                </button>
            {/if}
        </div>
    {/if}
</div>

<!-- Modals -->
{#if showCreateModal}
    <FeatureModal
        on:close={() => showCreateModal = false}
        on:save={async (event) => {
            await featureStore.createFeature(event.detail);
            showCreateModal = false;
        }}
    />
{/if}

{#if editingFeature}
    <FeatureModal
        feature={editingFeature}
        on:close={() => editingFeature = null}
        on:save={async (event) => {
            if (editingFeature) {
                await featureStore.updateFeature(editingFeature.id, event.detail);
                editingFeature = null;
            }
        }}
    />
{/if}
```

**2. Backend Feature Development Process**:

```python
# 1. Define Pydantic schemas
# schemas/feature.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class FeatureBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)
    enabled: bool = True

class FeatureCreate(FeatureBase):
    pass

class FeatureUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    enabled: Optional[bool] = None

class FeatureResponse(FeatureBase):
    id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
```

```python
# 2. Create database model
# models/feature.py
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from .base import Base
import uuid

class Feature(Base):
    __tablename__ = "features"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(500), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Feature(id='{self.id}', name='{self.name}', enabled={self.enabled})>"
```

```python
# 3. Create service layer
# services/feature_service.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from typing import List, Optional
import uuid
from datetime import datetime

from ..models.feature import Feature
from ..schemas.feature import FeatureCreate, FeatureUpdate

class FeatureService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_all_features(self) -> List[Feature]:
        """Get all features"""
        stmt = select(Feature).order_by(Feature.created_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()
    
    async def get_feature_by_id(self, feature_id: str) -> Optional[Feature]:
        """Get feature by ID"""
        stmt = select(Feature).where(Feature.id == feature_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_feature_by_name(self, name: str) -> Optional[Feature]:
        """Get feature by name"""
        stmt = select(Feature).where(Feature.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create_feature(self, feature_data: FeatureCreate) -> Feature:
        """Create a new feature"""
        # Check if feature with name already exists
        existing = await self.get_feature_by_name(feature_data.name)
        if existing:
            raise ValueError(f"Feature with name '{feature_data.name}' already exists")
        
        feature = Feature(
            id=str(uuid.uuid4()),
            **feature_data.dict()
        )
        
        self.db.add(feature)
        await self.db.commit()
        await self.db.refresh(feature)
        
        return feature
    
    async def update_feature(
        self, 
        feature_id: str, 
        feature_data: FeatureUpdate
    ) -> Optional[Feature]:
        """Update a feature"""
        # Check if feature exists
        existing = await self.get_feature_by_id(feature_id)
        if not existing:
            return None
        
        # Check name uniqueness if name is being updated
        if feature_data.name and feature_data.name != existing.name:
            name_check = await self.get_feature_by_name(feature_data.name)
            if name_check:
                raise ValueError(f"Feature with name '{feature_data.name}' already exists")
        
        # Update feature
        update_data = feature_data.dict(exclude_unset=True)
        if update_data:
            update_data['updated_at'] = datetime.utcnow()
            
            stmt = (
                update(Feature)
                .where(Feature.id == feature_id)
                .values(**update_data)
            )
            
            await self.db.execute(stmt)
            await self.db.commit()
        
        return await self.get_feature_by_id(feature_id)
    
    async def delete_feature(self, feature_id: str) -> bool:
        """Delete a feature"""
        stmt = delete(Feature).where(Feature.id == feature_id)
        result = await self.db.execute(stmt)
        await self.db.commit()
        
        return result.rowcount > 0
    
    async def get_enabled_features(self) -> List[Feature]:
        """Get only enabled features"""
        stmt = select(Feature).where(Feature.enabled == True).order_by(Feature.name)
        result = await self.db.execute(stmt)
        return result.scalars().all()
```

```python
# 4. Create API router
# routers/features.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..database import get_db
from ..auth import get_current_user, get_admin_user
from ..models import User
from ..schemas.feature import FeatureCreate, FeatureUpdate, FeatureResponse
from ..services.feature_service import FeatureService

router = APIRouter(prefix="/features", tags=["features"])

@router.get("", response_model=List[FeatureResponse])
async def get_all_features(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all features (admin) or enabled features (user)"""
    service = FeatureService(db)
    
    if current_user.role == "admin":
        features = await service.get_all_features()
    else:
        features = await service.get_enabled_features()
    
    return features

@router.get("/{feature_id}", response_model=FeatureResponse)
async def get_feature(
    feature_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific feature"""
    service = FeatureService(db)
    feature = await service.get_feature_by_id(feature_id)
    
    if not feature:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature not found"
        )
    
    # Non-admin users can only see enabled features
    if current_user.role != "admin" and not feature.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature not found"
        )
    
    return feature

@router.post("", response_model=FeatureResponse, status_code=status.HTTP_201_CREATED)
async def create_feature(
    feature_data: FeatureCreate,
    current_user: User = Depends(get_admin_user),  # Admin only
    db: AsyncSession = Depends(get_db)
):
    """Create a new feature (admin only)"""
    service = FeatureService(db)
    
    try:
        feature = await service.create_feature(feature_data)
        return feature
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.put("/{feature_id}", response_model=FeatureResponse)
async def update_feature(
    feature_id: str,
    feature_data: FeatureUpdate,
    current_user: User = Depends(get_admin_user),  # Admin only
    db: AsyncSession = Depends(get_db)
):
    """Update a feature (admin only)"""
    service = FeatureService(db)
    
    try:
        feature = await service.update_feature(feature_id, feature_data)
        if not feature:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Feature not found"
            )
        return feature
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.delete("/{feature_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feature(
    feature_id: str,
    current_user: User = Depends(get_admin_user),  # Admin only
    db: AsyncSession = Depends(get_db)
):
    """Delete a feature (admin only)"""
    service = FeatureService(db)
    
    success = await service.delete_feature(feature_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feature not found"
        )
```

## Testing Guidelines

### Frontend Testing

**Component Testing with Vitest**:
```typescript
// tests/components/FeatureCard.test.ts
import { render, screen, fireEvent } from '@testing-library/svelte';
import { vi, describe, it, expect } from 'vitest';
import FeatureCard from '$lib/components/features/FeatureCard.svelte';
import type { FeatureItem } from '$lib/types/feature';

const mockFeature: FeatureItem = {
    id: '1',
    name: 'Test Feature',
    description: 'Test description',
    enabled: true,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z'
};

describe('FeatureCard', () => {
    it('renders feature information correctly', () => {
        render(FeatureCard, { feature: mockFeature });
        
        expect(screen.getByText('Test Feature')).toBeInTheDocument();
        expect(screen.getByText('Test description')).toBeInTheDocument();
        expect(screen.getByText('Enabled')).toBeInTheDocument();
    });
    
    it('emits toggle event when toggle is clicked', async () => {
        const component = render(FeatureCard, { feature: mockFeature });
        
        const toggle = screen.getByRole('checkbox');
        await fireEvent.click(toggle);
        
        expect(component.component.$capture_state()).toEqual(
            expect.objectContaining({
                toggleEventFired: true
            })
        );
    });
    
    it('shows action buttons when permissions allow', () => {
        render(FeatureCard, { 
            feature: mockFeature,
            canEdit: true,
            canDelete: true 
        });
        
        expect(screen.getByTitle('Edit feature')).toBeInTheDocument();
        expect(screen.getByTitle('Delete feature')).toBeInTheDocument();
    });
});
```

**Store Testing**:
```typescript
// tests/stores/features.test.ts
import { get } from 'svelte/store';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { featureStore, features } from '$lib/stores/features';
import { featureAPI } from '$lib/apis/features';

// Mock the API
vi.mock('$lib/apis/features', () => ({
    featureAPI: {
        getAll: vi.fn(),
        create: vi.fn(),
        update: vi.fn(),
        delete: vi.fn()
    }
}));

describe('featureStore', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });
    
    it('loads features successfully', async () => {
        const mockFeatures = [
            { id: '1', name: 'Feature 1', enabled: true },
            { id: '2', name: 'Feature 2', enabled: false }
        ];
        
        vi.mocked(featureAPI.getAll).mockResolvedValue({
            data: mockFeatures,
            status: 'success'
        });
        
        await featureStore.loadFeatures();
        
        expect(get(features)).toEqual(mockFeatures);
        expect(featureAPI.getAll).toHaveBeenCalledOnce();
    });
    
    it('creates feature successfully', async () => {
        const newFeature = { id: '3', name: 'New Feature', enabled: true };
        const createData = { name: 'New Feature', description: 'Test' };
        
        vi.mocked(featureAPI.create).mockResolvedValue({
            data: newFeature,
            status: 'success'
        });
        
        const result = await featureStore.createFeature(createData);
        
        expect(result).toEqual(newFeature);
        expect(featureAPI.create).toHaveBeenCalledWith(createData);
    });
});
```

### Backend Testing

**Service Layer Testing**:
```python
# tests/services/test_feature_service.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

from open_webui.services.feature_service import FeatureService
from open_webui.schemas.feature import FeatureCreate, FeatureUpdate
from open_webui.models.feature import Feature

@pytest.fixture
def feature_service():
    mock_db = AsyncMock(spec=AsyncSession)
    return FeatureService(mock_db), mock_db

@pytest.mark.asyncio
async def test_create_feature_success(feature_service):
    service, mock_db = feature_service
    
    feature_data = FeatureCreate(
        name="Test Feature",
        description="Test description",
        enabled=True
    )
    
    # Mock database operations
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    
    # Mock that feature doesn't exist
    service.get_feature_by_name = AsyncMock(return_value=None)
    
    result = await service.create_feature(feature_data)
    
    assert result.name == "Test Feature"
    assert result.description == "Test description"
    assert result.enabled is True
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()

@pytest.mark.asyncio
async def test_create_feature_duplicate_name(feature_service):
    service, mock_db = feature_service
    
    feature_data = FeatureCreate(
        name="Existing Feature",
        description="Test description"
    )
    
    # Mock existing feature
    existing_feature = Feature(id="1", name="Existing Feature")
    service.get_feature_by_name = AsyncMock(return_value=existing_feature)
    
    with pytest.raises(ValueError, match="already exists"):
        await service.create_feature(feature_data)

@pytest.mark.asyncio
async def test_update_feature_success(feature_service):
    service, mock_db = feature_service
    
    feature_id = "test-id"
    update_data = FeatureUpdate(name="Updated Name")
    
    # Mock existing feature
    existing_feature = Feature(id=feature_id, name="Old Name")
    service.get_feature_by_id = AsyncMock(return_value=existing_feature)
    service.get_feature_by_name = AsyncMock(return_value=None)
    
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    
    result = await service.update_feature(feature_id, update_data)
    
    assert result == existing_feature
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()
```

**API Endpoint Testing**:
```python
# tests/routers/test_features.py
import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from open_webui.models import User, Feature
from open_webui.schemas.feature import FeatureCreate

@pytest.mark.asyncio
async def test_get_all_features_as_admin(client: AsyncClient, admin_user: User):
    """Test getting all features as admin"""
    mock_features = [
        Feature(id="1", name="Feature 1", enabled=True),
        Feature(id="2", name="Feature 2", enabled=False)
    ]
    
    with patch('open_webui.services.feature_service.FeatureService') as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.get_all_features = AsyncMock(return_value=mock_features)
        
        response = await client.get("/api/v1/features", headers=get_auth_headers(admin_user))
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "Feature 1"
        assert data[1]["name"] == "Feature 2"

@pytest.mark.asyncio
async def test_create_feature_as_admin(client: AsyncClient, admin_user: User):
    """Test creating a feature as admin"""
    feature_data = {
        "name": "New Feature",
        "description": "Test description",
        "enabled": True
    }
    
    mock_feature = Feature(id="new-id", **feature_data)
    
    with patch('open_webui.services.feature_service.FeatureService') as mock_service_class:
        mock_service = mock_service_class.return_value
        mock_service.create_feature = AsyncMock(return_value=mock_feature)
        
        response = await client.post(
            "/api/v1/features", 
            json=feature_data,
            headers=get_auth_headers(admin_user)
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Feature"
        assert data["enabled"] is True

@pytest.mark.asyncio
async def test_create_feature_as_regular_user_forbidden(client: AsyncClient, regular_user: User):
    """Test that regular users cannot create features"""
    feature_data = {
        "name": "New Feature",
        "description": "Test description"
    }
    
    response = await client.post(
        "/api/v1/features", 
        json=feature_data,
        headers=get_auth_headers(regular_user)
    )
    
    assert response.status_code == 403
```

## Code Quality Guidelines

### Code Style and Standards

**TypeScript/JavaScript**:
- Use TypeScript strict mode
- Follow ESLint and Prettier configurations
- Use meaningful variable and function names
- Write JSDoc comments for public APIs
- Prefer functional programming patterns
- Use type guards for runtime type checking

**Python**:
- Follow PEP 8 style guidelines
- Use type hints for all function parameters and return values
- Write docstrings for all classes and functions
- Use Black for code formatting
- Follow dependency injection patterns
- Use async/await for all I/O operations

**General**:
- Keep functions small and focused (single responsibility)
- Avoid deep nesting (max 3 levels)
- Use descriptive commit messages
- Write tests for all new functionality
- Update documentation when adding features

### Performance Considerations

**Frontend**:
- Use Svelte's built-in optimizations (reactivity, stores)
- Implement lazy loading for large components
- Optimize images and assets
- Use Web Workers for heavy computations
- Implement proper caching strategies

**Backend**:
- Use database indexes appropriately
- Implement proper pagination
- Use async/await for I/O operations
- Implement caching where appropriate (Redis)
- Monitor and optimize database queries
- Use connection pooling

### Security Best Practices

**Authentication & Authorization**:
- Always validate user permissions
- Use secure JWT implementation
- Implement proper session management
- Use HTTPS in production
- Validate all user inputs

**Data Protection**:
- Sanitize user inputs
- Use parameterized queries
- Implement proper CORS settings
- Hash passwords with bcrypt
- Don't log sensitive information

This development guide ensures consistent, maintainable, and secure feature development in Open WebUI.