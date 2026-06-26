import { useParams } from 'react-router-dom'
import TradeDetailShell from '../tradedetail/TradeDetailShell'
import { perpsAdapter } from '../tradedetail/perpsAdapter'

export default function PerpsPositionDetail() {
  const { id } = useParams()
  return <TradeDetailShell adapter={perpsAdapter} id={id} />
}
