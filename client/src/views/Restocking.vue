<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div v-if="submitSuccess" class="success-banner">
        {{ t('restocking.orderPlacedSuccess', { orderNumber: submitSuccess.order_number }) }}
        <button class="dismiss-btn" @click="submitSuccess = null">&times;</button>
      </div>
      <div v-if="submitError" class="error">
        {{ t('restocking.orderPlacedFailed') }}: {{ submitError }}
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budgetLabel') }}</h3>
        </div>
        <div class="budget-control">
          <input
            type="range"
            class="budget-slider"
            v-model.number="budget"
            :min="0"
            :max="maxBudget"
            step="100"
          >
          <div class="budget-readout">{{ currencySymbol }}{{ budget.toLocaleString() }}</div>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.recommendedItems') }}</div>
          <div class="stat-value">{{ recommendedItems.length }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.estimatedCost') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ recommendedTotalCost.toLocaleString() }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ currencySymbol }}{{ remainingBudget.toLocaleString() }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
        </div>
        <div v-if="recommendedItems.length === 0" class="loading">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.currentDemand') }}</th>
                <th>{{ t('restocking.table.forecastedDemand') }}</th>
                <th>{{ t('restocking.table.shortfall') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineTotal') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in recommendedItems" :key="item.sku">
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ item.item_name }}</td>
                <td>{{ item.current_demand }}</td>
                <td><strong>{{ item.forecasted_demand }}</strong></td>
                <td>{{ item.shortfall }}</td>
                <td>{{ currencySymbol }}{{ item.unit_cost }}</td>
                <td>{{ currencySymbol }}{{ item.cost.toLocaleString() }}</td>
                <td>
                  <span :class="['badge', item.trend]">
                    {{ t(`trends.${item.trend}`) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="place-order-row">
          <button
            class="place-order-btn"
            :disabled="recommendedItems.length === 0 || submitting || !!submitSuccess"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, watch, computed } from 'vue'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'

const TREND_PRIORITY = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const allForecasts = ref([])
    const inventoryItems = ref([])

    const budget = ref(0)
    let hasInitializedBudget = false

    const submitting = ref(false)
    const submitSuccess = ref(null)
    const submitError = ref(null)

    // Use shared filters
    const { selectedLocation, selectedCategory, getCurrentFilters } = useFilters()

    // Filter forecasts based on inventory filters
    const forecasts = computed(() => {
      if (selectedLocation.value === 'all' && selectedCategory.value === 'all') {
        return allForecasts.value
      }

      const validSkus = new Set(inventoryItems.value.map(item => item.sku))
      return allForecasts.value.filter(f => validSkus.has(f.item_sku))
    })

    const inventoryBySku = computed(() => {
      const map = new Map()
      for (const item of inventoryItems.value) {
        map.set(item.sku, item)
      }
      return map
    })

    const restockCandidates = computed(() => {
      const candidates = []
      for (const forecast of forecasts.value) {
        const inventoryItem = inventoryBySku.value.get(forecast.item_sku)
        if (!inventoryItem) continue

        const shortfall = Math.max(0, forecast.forecasted_demand - forecast.current_demand)
        if (shortfall <= 0) continue

        const cost = shortfall * inventoryItem.unit_cost

        candidates.push({
          sku: forecast.item_sku,
          item_name: forecast.item_name,
          current_demand: forecast.current_demand,
          forecasted_demand: forecast.forecasted_demand,
          trend: forecast.trend,
          shortfall,
          unit_cost: inventoryItem.unit_cost,
          cost
        })
      }
      return candidates
    })

    const sortedCandidates = computed(() => {
      return [...restockCandidates.value].sort((a, b) => {
        const trendDiff = (TREND_PRIORITY[a.trend] ?? 99) - (TREND_PRIORITY[b.trend] ?? 99)
        if (trendDiff !== 0) return trendDiff
        return a.cost - b.cost
      })
    })

    const totalRestockCost = computed(() => {
      return sortedCandidates.value.reduce((sum, c) => sum + c.cost, 0)
    })

    const maxBudget = computed(() => {
      return Math.max(1000, Math.ceil(totalRestockCost.value / 100) * 100)
    })

    const recommendation = computed(() => {
      const items = []
      let runningTotal = 0

      for (const candidate of sortedCandidates.value) {
        if (runningTotal + candidate.cost <= budget.value) {
          items.push(candidate)
          runningTotal += candidate.cost
        }
      }

      return { items, totalCost: runningTotal }
    })

    const recommendedItems = computed(() => recommendation.value.items)
    const recommendedTotalCost = computed(() => recommendation.value.totalCost)
    const remainingBudget = computed(() => budget.value - recommendedTotalCost.value)

    let requestId = 0
    const loadRestockingData = async () => {
      const myRequest = ++requestId
      try {
        loading.value = true
        const filters = getCurrentFilters()

        const [forecastsData, inventoryData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory({
            warehouse: filters.warehouse,
            category: filters.category
          })
        ])

        if (myRequest !== requestId) return // a newer request superseded this one; discard

        allForecasts.value = forecastsData
        inventoryItems.value = inventoryData

        if (!hasInitializedBudget) {
          budget.value = Math.round(totalRestockCost.value / 2 / 100) * 100
          hasInitializedBudget = true
        }
      } catch (err) {
        if (myRequest !== requestId) return
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        if (myRequest === requestId) loading.value = false
      }
    }

    // Watch for filter changes and reload data
    watch([selectedLocation, selectedCategory], () => {
      loadRestockingData()
    })

    // Clamp budget down if the ceiling shrinks below the current value
    watch(maxBudget, (newMax) => {
      if (budget.value > newMax) {
        budget.value = newMax
      }
    })

    const placeOrder = async () => {
      if (recommendedItems.value.length === 0) return
      submitting.value = true
      submitError.value = null
      try {
        submitSuccess.value = await api.createRestockingOrder({
          budget: budget.value,
          items: recommendedItems.value.map(i => ({
            sku: i.sku,
            name: i.item_name,
            quantity: i.shortfall,
            unit_cost: i.unit_cost
          }))
        })
      } catch (err) {
        submitError.value = err.message
      } finally {
        submitting.value = false
      }
    }

    onMounted(() => loadRestockingData())

    return {
      t,
      currencySymbol,
      loading,
      error,
      budget,
      maxBudget,
      recommendedItems,
      recommendedTotalCost,
      remainingBudget,
      submitting,
      submitSuccess,
      submitError,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-control {
  display: flex;
  align-items: center;
  gap: 1.25rem;
}

.budget-slider {
  flex: 1;
  -webkit-appearance: none;
  appearance: none;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  outline: none;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #667eea;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  cursor: pointer;
  transition: transform 0.2s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #667eea;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  cursor: pointer;
  transition: transform 0.2s ease;
}

.budget-slider::-moz-range-thumb:hover {
  transform: scale(1.1);
}

.budget-slider:focus::-webkit-slider-thumb {
  box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.25);
}

.budget-slider:focus::-moz-range-thumb {
  box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.25);
}

.budget-readout {
  min-width: 120px;
  text-align: right;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.place-order-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 1.25rem;
}

.place-order-btn {
  padding: 0.75rem 1.75rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  transform: translateY(-2px);
}

.place-order-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.success-banner {
  background: #d1fae5;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.dismiss-btn {
  background: none;
  border: none;
  color: #065f46;
  font-size: 1.25rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 0.25rem;
}
</style>
